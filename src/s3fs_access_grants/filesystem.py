"""ScopedS3FileSystem: route every s3fs call to a per-grant scoped credential.

Transparent S3 Access Grants for fsspec/s3fs. No Access Grants logic in
application code: register the implementation for "s3" and pandas / polars /
UPath / fsspec.open all route through it.

NOTE: this subclass depends on s3fs internals — specifically that both
S3FileSystem._call_s3 and S3FileSystem._iterdir resolve their client through
self.get_s3(). s3fs is pinned exactly in pyproject.toml; re-check this seam on
any bump. Validated against s3fs 2026.6.0, aiobotocore 2.25.1, plugin 1.3.0.
"""

import asyncio
import contextlib
import logging
import os
import weakref
from dataclasses import dataclass
from typing import Any

import aiobotocore.session
import boto3
from aiobotocore.config import AioConfig
from aiobotocore.credentials import AioRefreshableCredentials
from botocore.exceptions import ClientError
from s3fs.core import S3FileSystem

logger = logging.getLogger(__name__)


class CrossScopeCopyError(Exception):
    """Raised when a copy spans two different grant scopes (unsupported by design)."""


@dataclass(frozen=True)
class _Scope:
    prefix: str  # match key, no scheme/wildcard, e.g. "bucket/teamA/"
    target: str  # GetDataAccess Target, e.g. "s3://bucket/teamA/"
    permission: str  # READ | WRITE | READWRITE


# Module-level cache: enumeration is identity-global, so all FS instances built
# for the same (account, region) share one routing table regardless of how
# fsspec's instance cache keys them.
_SCOPE_CACHE: dict[tuple[str, str], list[_Scope]] = {}


# Process-wide overrides set by init() — consulted by the resolvers so an
# explicit account/region reaches later argless fsspec.filesystem("s3") calls
# without mutating os.environ.
_OVERRIDE_ACCOUNT_ID: str | None = None
_OVERRIDE_REGION: str | None = None


def set_overrides(account_id=None, region=None):
    """Record process-wide account/region overrides consulted by the resolvers."""
    global _OVERRIDE_ACCOUNT_ID, _OVERRIDE_REGION
    if account_id:
        _OVERRIDE_ACCOUNT_ID = account_id
    if region:
        _OVERRIDE_REGION = region


def resolve_account_id(explicit=None):
    """Grants-instance owner account. Explicit > init() override > env > STS caller.

    The grants instance may live in a different account than the caller's role
    (cross-account setup), so the override/env is the authoritative source; the
    STS caller account is only a same-account fallback.
    """
    return (
        explicit
        or _OVERRIDE_ACCOUNT_ID
        or os.environ.get("S3FS_ACCESS_GRANTS_ACCOUNT_ID")
        or boto3.client("sts").get_caller_identity()["Account"]
    )


def resolve_region(explicit=None):
    """Region of the grants instance. Explicit > init() override > S3FS_ACCESS_GRANTS_REGION env > session default.

    Deliberately NOT keyed on AWS_REGION directly: that is the caller's profile
    region, which may differ from where the access grants instance lives. The
    session default is the last resort and will itself honour AWS_REGION when set.
    """
    return (
        explicit
        or _OVERRIDE_REGION
        or os.environ.get("S3FS_ACCESS_GRANTS_REGION")
        or boto3.session.Session().region_name
    )


def _parse_grant(grant: dict) -> _Scope:
    raw = grant["GrantScope"]  # "s3://bucket/prefix/*"
    target = raw[:-1] if raw.endswith("*") else raw  # "s3://bucket/prefix/"
    prefix = target[len("s3://") :] if target.startswith("s3://") else target
    return _Scope(prefix=prefix, target=target, permission=grant["Permission"])


def _enumerate_scopes(s3control, account_id: str, region: str) -> list[_Scope]:
    cache_key = (account_id, region)
    if cache_key in _SCOPE_CACHE:
        return _SCOPE_CACHE[cache_key]
    scopes: list[_Scope] = []
    try:
        paginator = s3control.get_paginator("list_caller_access_grants")
        for page in paginator.paginate(AccountId=account_id):
            for grant in page.get("CallerAccessGrantsList", []):
                scopes.append(_parse_grant(grant))
    except ClientError as e:
        # No permission to list grants (or no grants instance): degrade to a
        # no-op router. With an empty scope list every call routes to the
        # default client, i.e. plain S3FileSystem behaviour. Fail-open here is
        # safe — actual S3 authorization is still enforced per request.
        logger.warning(
            "ListCallerAccessGrants failed (%s); ScopedS3FileSystem will route all "
            "calls through default credentials.",
            e.response.get("Error", {}).get("Code", "Unknown"),
        )
    scopes.sort(key=lambda s: len(s.prefix), reverse=True)  # longest-prefix first
    _SCOPE_CACHE[cache_key] = scopes
    return scopes


def _finalize_scope_clients(loop, clients):
    for client in list(clients.values()):
        S3FileSystem.close_session(loop, client)


class _ClientOverride:
    """Proxy `self` that pins get_s3() to a precomputed scoped client.

    Used to call the parent _call_s3 / _iterdir verbatim while swapping only the
    one line that resolves the client. MUST stay a pure passthrough: every other
    attribute (dircache, req_kw, _fill_info, retries, ...) delegates to the real
    fs. Do not add state here.
    """

    def __init__(self, fs, client):
        self._fs = fs
        self._client = client

    async def get_s3(self, bucket=None):
        return self._client

    def __getattr__(self, name):
        return getattr(self._fs, name)


class ScopedS3FileSystem(S3FileSystem):
    """s3fs filesystem that routes each call through its matching grant's credentials."""

    def __init__(self, *args, grants_account_id=None, grants_region=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._grants_region = resolve_region(grants_region)
        self._grants_account_id = resolve_account_id(grants_account_id)
        # sync boto3 client for ListCallerAccessGrants + GetDataAccess
        self._s3control = boto3.client("s3control", region_name=self._grants_region)
        self._scopes = _enumerate_scopes(
            self._s3control, self._grants_account_id, self._grants_region
        )
        self._scope_clients: dict[str, Any] = {}  # prefix -> aiobotocore client
        self._scope_locks: dict[str, asyncio.Lock] = {}
        if not self.asynchronous:
            weakref.finalize(self, _finalize_scope_clients, self.loop, self._scope_clients)

    # --- routing ---
    def _routing_target(self, kwargs):
        bucket = kwargs.get("Bucket")
        if not bucket:
            return None
        sub = kwargs.get("Key") or kwargs.get("Prefix") or ""
        return f"{bucket}/{sub}" if sub else bucket

    def _scope_for(self, target):
        if not target:
            return None
        for scope in self._scopes:  # longest-prefix first
            if target == scope.prefix.rstrip("/") or target.startswith(scope.prefix):
                return scope
        return None

    # --- lazy per-scope client with auto-refresh ---
    def _make_refresh(self, scope: _Scope):
        # GetDataAccess returns AWS-cased keys; RefreshableCredentials wants the
        # lowercase botocore metadata shape, so remap here.
        def _refresh():
            resp = self._s3control.get_data_access(
                AccountId=self._grants_account_id,
                Target=scope.target,
                Permission=scope.permission,
                Privilege="Default",
            )
            c = resp["Credentials"]
            expiry = c["Expiration"]
            return {
                "access_key": c["AccessKeyId"],
                "secret_key": c["SecretAccessKey"],
                "token": c["SessionToken"],
                "expiry_time": expiry.isoformat() if hasattr(expiry, "isoformat") else expiry,
            }

        return _refresh

    def _scope_client_kwargs(self):
        # Mirror how the base set_session builds its client (config + client_kwargs).
        client_kwargs = self.client_kwargs.copy()
        kw = {"config": AioConfig(**self._prepare_config_kwargs()), **client_kwargs}
        if self.endpoint_url and "endpoint_url" not in client_kwargs:
            kw["endpoint_url"] = self.endpoint_url
        if "use_ssl" not in client_kwargs:
            kw["use_ssl"] = self.use_ssl
        return kw

    async def _client_for_scope(self, scope):
        if scope is None:
            return self._s3  # default IAM client → fail-closed
        if scope.prefix in self._scope_clients:
            return self._scope_clients[scope.prefix]
        lock = self._scope_locks.setdefault(scope.prefix, asyncio.Lock())
        async with lock:
            if scope.prefix in self._scope_clients:  # re-check under lock
                return self._scope_clients[scope.prefix]
            refresh = self._make_refresh(scope)
            creds = AioRefreshableCredentials.create_from_metadata(
                metadata=refresh(),  # seed eagerly
                refresh_using=refresh,
                method="s3-access-grants",
            )
            session = aiobotocore.session.AioSession()
            session._credentials = creds  # noqa: SLF001 — resolved via get_credentials()
            client = await session.create_client("s3", **self._scope_client_kwargs()).__aenter__()
            self._scope_clients[scope.prefix] = client
            return client

    # --- interception via proxy-self: run the parent body verbatim, swap only
    # the client-resolution line (get_s3) for the scoped client. ---
    async def _call_s3(self, method, *akwarglist, **kwargs):
        await self.set_session()
        client = await self._client_for_scope(self._scope_for(self._routing_target(kwargs)))
        # _ClientOverride is a structural stand-in for the filesystem (see class
        # docstring); ty can't see the duck-typing, so the proxy arg is ignored.
        return await S3FileSystem._call_s3(  # noqa: SLF001 — drive parent body with scoped client
            _ClientOverride(self, client),  # ty: ignore[invalid-argument-type]
            method,
            *akwarglist,
            **kwargs,
        )

    async def _iterdir(self, bucket, max_items=None, delimiter="/", prefix="", versions=False):
        # Listings bypass _call_s3 and resolve the client directly in _iterdir;
        # they carry a Prefix, so route on bucket+prefix here.
        await self.set_session()
        target = self._routing_target({"Bucket": bucket, "Prefix": prefix})
        client = await self._client_for_scope(self._scope_for(target))
        async for c in S3FileSystem._iterdir(  # noqa: SLF001 — drive parent body with scoped client
            _ClientOverride(self, client),  # ty: ignore[invalid-argument-type]
            bucket,
            max_items=max_items,
            delimiter=delimiter,
            prefix=prefix,
            versions=versions,
        ):
            yield c

    # --- cross-scope copy guard ---
    async def _cp_file(self, path1, path2, preserve_etag=None, **kwargs):
        s1 = self._scope_for(self._strip_protocol(path1))
        s2 = self._scope_for(self._strip_protocol(path2))
        if s1 != s2:
            raise CrossScopeCopyError(
                f"cross-scope copy not allowed: "
                f"{s1.prefix if s1 else None} -> {s2.prefix if s2 else None}"
            )
        return await super()._cp_file(path1, path2, preserve_etag=preserve_etag, **kwargs)

    async def _close_scopes(self):
        for client in list(self._scope_clients.values()):
            with contextlib.suppress(Exception):
                await client.__aexit__(None, None, None)
        self._scope_clients.clear()
