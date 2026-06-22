import pytest

from s3fs_access_grants import filesystem


@pytest.fixture(autouse=True)
def _reset_scope_cache():
    # enumerate_scopes caches per (account, region) — clear it around each test
    # so cases can't leak routing tables into one another.
    filesystem._SCOPE_CACHE.clear()
    yield
    filesystem._SCOPE_CACHE.clear()
