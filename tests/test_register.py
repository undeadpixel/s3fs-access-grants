from unittest.mock import MagicMock

import pytest
from botocore.exceptions import NoCredentialsError, NoRegionError

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

    def test_registers_subclass_with_bound_account_and_region(self, mocker):
        _patch_s3control(mocker, [{"GrantScope": "s3://bucket/teamA/*", "Permission": "READ"}])
        register_impl = mocker.patch("s3fs_access_grants.fsspec.register_implementation")

        register(account_id="111", region="eu-west-1")

        # Both s3 and s3a get the same bound subclass — a real class (not a
        # partial), so fsspec's URL-chain classmethods stay available.
        protocols = {call.args[0] for call in register_impl.call_args_list}
        assert protocols == {"s3", "s3a"}
        registered = {call.args[1] for call in register_impl.call_args_list}
        assert len(registered) == 1
        bound = registered.pop()
        assert isinstance(bound, type)
        assert issubclass(bound, ScopedS3FileSystem)
        assert bound.grants_account_id == "111"
        assert bound.grants_region == "eu-west-1"
        # The classmethods a partial lacked must resolve on the subclass.
        assert bound._strip_protocol("s3://bucket/teamA/x") == "bucket/teamA/x"

    def test_registers_nothing_without_grants(self, mocker):
        _patch_s3control(mocker, [])
        register_impl = mocker.patch("s3fs_access_grants.fsspec.register_implementation")

        assert register(account_id="111", region="eu-west-1") is None
        register_impl.assert_not_called()

    def test_no_credentials_during_sts_call_is_a_noop(self, mocker):
        # The real failure path: boto3.client("sts") succeeds, but
        # get_caller_identity() raises NoCredentialsError deep in signing. With
        # no explicit account/region, _resolve_account_id() hits STS first. This
        # must not crash register() — it fails open so the call is safe in CI.
        sts = MagicMock()
        sts.get_caller_identity.side_effect = NoCredentialsError()
        mocker.patch("s3fs_access_grants.boto3.client", return_value=sts)
        register_impl = mocker.patch("s3fs_access_grants.fsspec.register_implementation")

        assert register() is None
        register_impl.assert_not_called()

    @pytest.mark.parametrize("error", [NoCredentialsError(), NoRegionError()])
    def test_client_construction_failure_is_a_noop(self, mocker, error):
        # Credentials/region errors raised at client construction must also fail
        # open rather than propagate.
        mocker.patch("s3fs_access_grants.boto3.client", side_effect=error)
        register_impl = mocker.patch("s3fs_access_grants.fsspec.register_implementation")

        assert register() is None
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
