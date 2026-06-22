"""Transparent S3 Access Grants for fsspec/s3fs.

Importing this package registers ScopedS3FileSystem as the "s3" handler **only if
the caller actually has access grants**. With no grants (no permission to list,
or an empty list) we register nothing and leave plain s3fs in place — no subclass
overhead when there's nothing to route.

Registration is explicit — importing the package does no AWS I/O. Call
register() to install the handler for the calling identity's grants:

    import s3fs_access_grants
    s3fs_access_grants.register()

For environments where you'd rather pass account/region explicitly (e.g. a
Jupyter notebook) call init(), which also returns the live filesystem:

    import s3fs_access_grants
    fs = s3fs_access_grants.init(account_id="767546672094", region="eu-west-1")
"""

import logging
from importlib import metadata
from importlib.metadata import PackageNotFoundError

import boto3
import fsspec

from .filesystem import (
    CrossScopeCopyError,
    ScopedS3FileSystem,
    _enumerate_scopes,
    resolve_account_id,
    resolve_region,
    set_overrides,
)

try:
    __version__ = metadata.version("s3fs-access-grants")
except PackageNotFoundError:
    __version__ = "0.0.0.dev0"

__all__ = ["CrossScopeCopyError", "ScopedS3FileSystem", "init", "register"]

logger = logging.getLogger(__name__)


def register(account_id=None, region=None):
    """Register ScopedS3FileSystem for s3/s3a — but only if grants exist.

    Enumerates the caller's access grants up front. If there are none (or no
    permission to list them), registers nothing and returns False, so plain
    s3fs handles s3:// with no added overhead.
    """
    account_id = resolve_account_id(account_id)
    region = resolve_region(region)
    s3control = boto3.client("s3control", region_name=region)
    scopes = _enumerate_scopes(s3control, account_id, region)
    if not scopes:
        logger.info(
            "No access grants for account %s in %s; leaving default s3fs in place.",
            account_id,
            region,
        )
        return False
    fsspec.register_implementation("s3", ScopedS3FileSystem, clobber=True)
    fsspec.register_implementation("s3a", ScopedS3FileSystem, clobber=True)
    return True


def init(account_id=None, region=None):
    """Register with explicit account/region and return the instance (notebooks).

    Records the values as process-wide overrides (no os.environ mutation) so any
    later argless fsspec.filesystem("s3") picks them up. Returns the
    ScopedS3FileSystem if grants exist, else a default s3fs.
    """
    set_overrides(account_id=account_id, region=region)
    register(account_id=account_id, region=region)
    return fsspec.filesystem("s3")
