from functools import partial
from unittest.mock import MagicMock

from s3fs_access_grants import _resolve_account_id, _resolve_region, register
from s3fs_access_grants.filesystem import ScopedS3FileSystem


def _patch_s3control(mocker, grants):
    paginator = MagicMock()
    paginator.paginate.return_value = [{"CallerAccessGrantsList": grants}]
    client = MagicMock()
    client.get_paginator.return_value = paginator
    mocker.patch("s3fs_access_grants.boto3.client", return_value=client)
    return client


class TestRegister:
    def test_returns_none(self, mocker):
        _patch_s3control(mocker, [{"GrantScope": "s3://bucket/teamA/*", "Permission": "READ"}])
        mocker.patch("s3fs_access_grants.fsspec.register_implementation")
        assert register(account_id="111", region="eu-west-1") is None

    def test_binds_resolved_account_and_region_into_factory(self, mocker):
        _patch_s3control(mocker, [{"GrantScope": "s3://bucket/teamA/*", "Permission": "READ"}])
        register_impl = mocker.patch("s3fs_access_grants.fsspec.register_implementation")

        register(account_id="111", region="eu-west-1")

        # Both s3 and s3a get the same bound factory; no globals involved.
        protocols = {call.args[0] for call in register_impl.call_args_list}
        assert protocols == {"s3", "s3a"}
        for call in register_impl.call_args_list:
            factory = call.args[1]
            assert isinstance(factory, partial)
            assert factory.func is ScopedS3FileSystem
            assert factory.keywords == {
                "grants_account_id": "111",
                "grants_region": "eu-west-1",
            }

    def test_registers_nothing_without_grants(self, mocker):
        _patch_s3control(mocker, [])
        register_impl = mocker.patch("s3fs_access_grants.fsspec.register_implementation")

        assert register(account_id="111", region="eu-west-1") is None
        register_impl.assert_not_called()


class TestResolution:
    def test_account_id_explicit_wins(self):
        assert _resolve_account_id("explicit") == "explicit"

    def test_account_id_env_used_when_no_explicit(self, monkeypatch):
        monkeypatch.setenv("S3FS_ACCESS_GRANTS_ACCOUNT_ID", "from-env")
        assert _resolve_account_id() == "from-env"

    def test_region_explicit_wins(self):
        assert _resolve_region("eu-west-1") == "eu-west-1"

    def test_region_env_used_when_no_explicit(self, monkeypatch):
        monkeypatch.setenv("S3FS_ACCESS_GRANTS_REGION", "ap-south-1")
        assert _resolve_region() == "ap-south-1"
