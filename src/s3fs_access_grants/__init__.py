"""Transparent S3 Access Grants for fsspec/s3fs.

Call register() once to install ScopedS3FileSystem as the "s3" handler, then use
fsspec / pandas / polars / universal-pathlib as usual — every call routes through
a credential scoped to the matching grant. Importing this package does no AWS I/O;
registration is explicit.

    import s3fs_access_grants

    # Use ambient AWS config (env / profile / instance role):
    s3fs_access_grants.register()

    # Or pass the grants instance account/region explicitly (notebooks,
    # cross-account setups). register() returns the live filesystem:
    fs = s3fs_access_grants.register(account_id="767546672094", region="eu-west-1")
    fs.ls("s3://bucket/teamA/")

If the caller has no access grants (or no permission to list them), register()
installs nothing and returns a plain s3fs filesystem, so s3:// keeps working with
no added overhead.
"""

import logging
from importlib import metadata
from importlib.metadata import PackageNotFoundError

import boto3
import fsspec

from . import filesystem
from .filesystem import CrossScopeCopyError, ScopedS3FileSystem

try:
    __version__ = metadata.version("s3fs-access-grants")
except PackageNotFoundError:
    __version__ = "0.0.0.dev0"

__all__ = ["CrossScopeCopyError", "ScopedS3FileSystem", "register"]

logger = logging.getLogger(__name__)


def register(account_id=None, region=None):
    """Install the scoped s3:// handler and return the live filesystem.

    Enumerates the calling identity's access grants. If any exist, registers
    ScopedS3FileSystem for s3/s3a (clobbering the default) and returns it. If
    there are none (or no permission to list them), registers nothing and returns
    a plain s3fs filesystem, so s3:// keeps working with no added overhead.

    Args:
        account_id: Grants-instance owner account. Defaults to the
            S3FS_ACCESS_GRANTS_ACCOUNT_ID env var, then the STS caller account.
        region: Region the grants instance lives in. Defaults to the
            S3FS_ACCESS_GRANTS_REGION env var, then the session default.

    Returns:
        The live fsspec filesystem for s3:// — a ScopedS3FileSystem when grants
        exist, otherwise a plain s3fs filesystem.
    """
    # Record overrides so a later argless fsspec.filesystem("s3") — which builds
    # a ScopedS3FileSystem with no args — still resolves the same account/region.
    filesystem.set_overrides(account_id=account_id, region=region)

    account_id = filesystem.resolve_account_id(account_id)
    region = filesystem.resolve_region(region)
    s3control = boto3.client("s3control", region_name=region)
    scopes = filesystem.enumerate_scopes(s3control, account_id, region)
    if not scopes:
        logger.info(
            "No access grants for account %s in %s; leaving default s3fs in place.",
            account_id,
            region,
        )
        return fsspec.filesystem("s3")

    fsspec.register_implementation("s3", ScopedS3FileSystem, clobber=True)
    fsspec.register_implementation("s3a", ScopedS3FileSystem, clobber=True)
    return fsspec.filesystem("s3")
