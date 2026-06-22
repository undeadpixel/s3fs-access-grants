from unittest.mock import MagicMock

import s3fs_access_grants
from s3fs_access_grants import filesystem
from s3fs_access_grants.filesystem import ScopedS3FileSystem


def _patch_s3control(mocker, grants):
    paginator = MagicMock()
    paginator.paginate.return_value = [{"CallerAccessGrantsList": grants}]
    client = MagicMock()
    client.get_paginator.return_value = paginator
    mocker.patch("s3fs_access_grants.boto3.client", return_value=client)
    return client


class TestRegister:
    def test_registers_scoped_fs_when_grants_exist(self, mocker):
        _patch_s3control(mocker, [{"GrantScope": "s3://bucket/teamA/*", "Permission": "READ"}])
        register_impl = mocker.patch("s3fs_access_grants.fsspec.register_implementation")
        mocker.patch("s3fs_access_grants.fsspec.filesystem", return_value="FS")

        result = s3fs_access_grants.register(account_id="111", region="eu-west-1")

        assert result == "FS"
        registered = {call.args for call in register_impl.call_args_list}
        assert ("s3", ScopedS3FileSystem) in registered
        assert ("s3a", ScopedS3FileSystem) in registered

    def test_returns_plain_fs_and_registers_nothing_without_grants(self, mocker):
        _patch_s3control(mocker, [])
        register_impl = mocker.patch("s3fs_access_grants.fsspec.register_implementation")
        mocker.patch("s3fs_access_grants.fsspec.filesystem", return_value="PLAIN")

        result = s3fs_access_grants.register(account_id="111", region="eu-west-1")

        assert result == "PLAIN"
        register_impl.assert_not_called()

    def test_records_overrides_for_later_argless_construction(self, mocker):
        _patch_s3control(mocker, [])
        mocker.patch("s3fs_access_grants.fsspec.register_implementation")
        mocker.patch("s3fs_access_grants.fsspec.filesystem", return_value="PLAIN")

        s3fs_access_grants.register(account_id="222", region="us-east-1")

        assert filesystem._OVERRIDE_ACCOUNT_ID == "222"
        assert filesystem._OVERRIDE_REGION == "us-east-1"


class TestResolution:
    def test_account_id_explicit_wins(self):
        assert filesystem.resolve_account_id("explicit") == "explicit"

    def test_account_id_override_then_env(self, monkeypatch):
        monkeypatch.setenv("S3FS_ACCESS_GRANTS_ACCOUNT_ID", "from-env")
        assert filesystem.resolve_account_id() == "from-env"
        filesystem.set_overrides(account_id="from-override")
        assert filesystem.resolve_account_id() == "from-override"

    def test_region_explicit_wins(self):
        assert filesystem.resolve_region("eu-west-1") == "eu-west-1"

    def test_region_env_used_when_no_explicit_or_override(self, monkeypatch):
        monkeypatch.setenv("S3FS_ACCESS_GRANTS_REGION", "ap-south-1")
        assert filesystem.resolve_region() == "ap-south-1"
