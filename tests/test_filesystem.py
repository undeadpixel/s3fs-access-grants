from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from s3fs_access_grants.filesystem import (
    CrossScopeCopyError,
    ScopedS3FileSystem,
    _parse_grant,
    _Scope,
    enumerate_scopes,
)


def _s3control_returning(*grant_pages):
    # Stand in for a boto3 s3control client whose list_caller_access_grants
    # paginator yields the given pages of CallerAccessGrantsList entries.
    paginator = MagicMock()
    paginator.paginate.return_value = [{"CallerAccessGrantsList": page} for page in grant_pages]
    client = MagicMock()
    client.get_paginator.return_value = paginator
    return client


class TestParseGrant:
    def test_strips_scheme_and_wildcard(self):
        scope = _parse_grant({"GrantScope": "s3://bucket/teamA/*", "Permission": "READWRITE"})
        assert scope == _Scope(
            prefix="bucket/teamA/",
            target="s3://bucket/teamA/",
            permission="READWRITE",
        )

    def test_without_wildcard(self):
        scope = _parse_grant({"GrantScope": "s3://bucket/teamA/", "Permission": "READ"})
        assert scope.prefix == "bucket/teamA/"
        assert scope.target == "s3://bucket/teamA/"


def _fs_with_scopes(scopes):
    # _scope_for only reads self._scopes, so a bare namespace stands in for a
    # fully-constructed filesystem (which would require live AWS calls).
    return SimpleNamespace(_scopes=sorted(scopes, key=lambda s: len(s.prefix), reverse=True))


class TestScopeFor:
    def setup_method(self):
        self.team_a = _Scope("bucket/teamA/", "s3://bucket/teamA/", "READ")
        self.team_a_sub = _Scope("bucket/teamA/sub/", "s3://bucket/teamA/sub/", "READWRITE")
        self.fs = _fs_with_scopes([self.team_a, self.team_a_sub])

    def test_longest_prefix_wins(self):
        match = ScopedS3FileSystem._scope_for(self.fs, "bucket/teamA/sub/file.csv")
        assert match is self.team_a_sub

    def test_falls_back_to_shorter_prefix(self):
        match = ScopedS3FileSystem._scope_for(self.fs, "bucket/teamA/other.csv")
        assert match is self.team_a

    def test_matches_prefix_without_trailing_slash(self):
        match = ScopedS3FileSystem._scope_for(self.fs, "bucket/teamA")
        assert match is self.team_a

    def test_no_match_returns_none(self):
        assert ScopedS3FileSystem._scope_for(self.fs, "bucket/teamZ/x") is None

    def test_empty_target_returns_none(self):
        assert ScopedS3FileSystem._scope_for(self.fs, None) is None


class TestRoutingTarget:
    def test_bucket_and_key(self):
        target = ScopedS3FileSystem._routing_target(None, {"Bucket": "b", "Key": "teamA/f"})
        assert target == "b/teamA/f"

    def test_bucket_and_prefix(self):
        target = ScopedS3FileSystem._routing_target(None, {"Bucket": "b", "Prefix": "teamA/"})
        assert target == "b/teamA/"

    def test_bucket_only(self):
        assert ScopedS3FileSystem._routing_target(None, {"Bucket": "b"}) == "b"

    def test_no_bucket_returns_none(self):
        assert ScopedS3FileSystem._routing_target(None, {"Key": "x"}) is None


class TestEnumerateScopes:
    def test_parses_and_sorts_longest_prefix_first(self):
        client = _s3control_returning(
            [
                {"GrantScope": "s3://bucket/teamA/*", "Permission": "READ"},
                {"GrantScope": "s3://bucket/teamA/sub/*", "Permission": "READWRITE"},
            ]
        )
        scopes = enumerate_scopes(client, "111", "eu-west-1")
        assert [s.prefix for s in scopes] == ["bucket/teamA/sub/", "bucket/teamA/"]

    def test_flattens_paginated_pages(self):
        client = _s3control_returning(
            [{"GrantScope": "s3://b/a/*", "Permission": "READ"}],
            [{"GrantScope": "s3://b/bb/*", "Permission": "READ"}],
        )
        scopes = enumerate_scopes(client, "111", "eu-west-1")
        assert {s.prefix for s in scopes} == {"b/a/", "b/bb/"}

    def test_caches_per_account_region(self):
        client = _s3control_returning([{"GrantScope": "s3://b/a/*", "Permission": "READ"}])
        enumerate_scopes(client, "111", "eu-west-1")
        enumerate_scopes(client, "111", "eu-west-1")
        # Second call is served from cache, so the paginator runs only once.
        assert client.get_paginator.call_count == 1

    def test_client_error_fails_open_to_empty(self):
        client = MagicMock()
        client.get_paginator.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "no"}},
            "ListCallerAccessGrants",
        )
        assert enumerate_scopes(client, "111", "eu-west-1") == []


class TestCrossScopeCopyGuard:
    def setup_method(self):
        self.team_a = _Scope("bucket/teamA/", "s3://bucket/teamA/", "READWRITE")
        self.team_b = _Scope("bucket/teamB/", "s3://bucket/teamB/", "READWRITE")
        self.fs = SimpleNamespace(
            _scopes=[self.team_a, self.team_b],
            _strip_protocol=lambda p: p.removeprefix("s3://"),
        )
        # _scope_for and _cp_file only read these attrs; bind the real _scope_for
        # so the guard runs against actual matching logic.
        self.fs._scope_for = lambda target: ScopedS3FileSystem._scope_for(self.fs, target)

    async def test_cross_scope_copy_raises(self):
        with pytest.raises(CrossScopeCopyError):
            await ScopedS3FileSystem._cp_file(
                self.fs, "s3://bucket/teamA/x", "s3://bucket/teamB/y"
            )

    async def test_unscoped_to_scoped_copy_raises(self):
        # One side matches no grant (scope None), the other does -> still cross-scope.
        with pytest.raises(CrossScopeCopyError):
            await ScopedS3FileSystem._cp_file(self.fs, "s3://other/x", "s3://bucket/teamA/y")
