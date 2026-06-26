"""Transparent S3 Access Grants for fsspec/s3fs.

Call register() once to install ScopedS3FileSystem as the "s3" handler, then use
fsspec / pandas / polars / universal-pathlib as usual — every call routes through
a credential scoped to the matching grant. Importing this package does no AWS I/O;
registration is explicit.

    import s3fs_access_grants

    # Use ambient AWS config (env / profile / instance role):
    s3fs_access_grants.register()

    # Or pass the grants instance account/region explicitly (notebooks,
    # cross-account setups):
    s3fs_access_grants.register(account_id="123456789012", region="eu-west-1")

    # Then just use fsspec / pandas / polars as usual:
    import polars as pl
    df = pl.read_parquet("s3://bucket/teamA/data.parquet")

If the caller has no access grants (or no permission to list them), register()
installs nothing and leaves the default s3fs in place, so s3:// keeps working
with no added overhead.
"""

import logging
import os
from importlib import metadata
from importlib.metadata import PackageNotFoundError

import boto3
import fsspec
from botocore.exceptions import BotoCoreError, ClientError

from s3fs_access_grants.filesystem import (
    CrossScopeCopyError,
    ScopedS3FileSystem,
    enumerate_scopes,
)

try:
    __version__ = metadata.version("s3fs-access-grants")
except PackageNotFoundError:
    __version__ = "0.0.0.dev0"

__all__ = ["CrossScopeCopyError", "ScopedS3FileSystem", "register"]

logger = logging.getLogger(__name__)


def _resolve_account_id(explicit=None):
    """Grants-instance owner account. Explicit > env > STS caller.

    The grants instance may live in a different account than the caller's role
    (cross-account setup), so the explicit arg / env is the authoritative source;
    the STS caller account is only a same-account fallback.
    """
    return (
        explicit
        or os.environ.get("S3FS_ACCESS_GRANTS_ACCOUNT_ID")
        or boto3.client("sts").get_caller_identity()["Account"]
    )


def _resolve_region(explicit=None):
    """Region of the grants instance. Explicit > S3FS_ACCESS_GRANTS_REGION env > session default.

    Deliberately NOT keyed on AWS_REGION directly: that is the caller's profile
    region, which may differ from where the access grants instance lives. The
    session default is the last resort and will itself honour AWS_REGION when set.
    """
    return (
        explicit
        or os.environ.get("S3FS_ACCESS_GRANTS_REGION")
        or boto3.session.Session().region_name
    )


def register(account_id=None, region=None):
    """Install the scoped s3:// handler for the calling identity's grants.

    Resolves the grants-instance account and region, then enumerates the
    caller's access grants. If any exist, registers ScopedS3FileSystem for
    s3/s3a (clobbering the default) with the resolved account/region bound in,
    so fsspec constructs it correctly with no arguments. If there are none (or no
    permission to list them), registers nothing and leaves the default s3fs in
    place, so s3:// keeps working with no added overhead.

    Fail-open on no AWS access: if credentials, region, or connectivity are
    missing (no profile/role/env, unreachable endpoint), registration is skipped
    and the default s3fs is left in place. This keeps `register()` safe to call
    unconditionally in tests and CI where AWS is not configured.

    Args:
        account_id: Grants-instance owner account. Defaults to the
            S3FS_ACCESS_GRANTS_ACCOUNT_ID env var, then the STS caller account.
        region: Region the grants instance lives in. Defaults to the
            S3FS_ACCESS_GRANTS_REGION env var, then the session default.
    """
    try:
        account_id = _resolve_account_id(account_id)
        region = _resolve_region(region)
        s3control = boto3.client("s3control", region_name=region)
        scopes = enumerate_scopes(s3control, account_id, region)
    except (BotoCoreError, ClientError) as e:
        logger.info(
            "No AWS access (%s); leaving default s3fs in place.",
            type(e).__name__,
        )
        return
    if not scopes:
        logger.info(
            "No access grants for account %s in %s; leaving default s3fs in place.",
            account_id,
            region,
        )
        return

    # Register a subclass with the resolved account/region as class attributes,
    # not a functools.partial: fsspec resolves s3:// URLs by calling classmethods
    # (_get_kwargs_from_urls, _strip_protocol, ...) on the registered object, which
    # a partial does not have. A subclass keeps the full class interface and lets
    # fsspec instantiate the handler with no arguments.
    bound = type(
        "BoundScopedS3FileSystem",
        (ScopedS3FileSystem,),
        {"grants_account_id": account_id, "grants_region": region},
    )
    fsspec.register_implementation("s3", bound, clobber=True)
    fsspec.register_implementation("s3a", bound, clobber=True)
