from types import SimpleNamespace

from s3fs_access_grants.filesystem import (
    ScopedS3FileSystem,
    _parse_grant,
    _Scope,
)


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
