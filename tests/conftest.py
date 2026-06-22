import pytest

from s3fs_access_grants import filesystem


@pytest.fixture(autouse=True)
def _reset_module_state():
    # enumerate_scopes caches per (account, region) and register() records
    # process-wide overrides — both are module-level mutable state. Reset before
    # and after each test so cases can't leak routing tables or overrides.
    filesystem._SCOPE_CACHE.clear()
    filesystem._OVERRIDE_ACCOUNT_ID = None
    filesystem._OVERRIDE_REGION = None
    yield
    filesystem._SCOPE_CACHE.clear()
    filesystem._OVERRIDE_ACCOUNT_ID = None
    filesystem._OVERRIDE_REGION = None
