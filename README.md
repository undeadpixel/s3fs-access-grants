# s3fs-access-grants

Transparent [S3 Access Grants](https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-grants.html)
for [fsspec](https://filesystem-spec.readthedocs.io/) / [s3fs](https://s3fs.readthedocs.io/).

Register the implementation for `s3://` once and every fsspec consumer —
`pandas`, `polars`, `universal-pathlib`, `fsspec.open`, ... — routes each call
through a credential scoped to the matching grant. No Access Grants logic leaks
into application code.

## How it works

`ScopedS3FileSystem` subclasses `s3fs.S3FileSystem`. On construction it
enumerates the caller's grants (`ListCallerAccessGrants`) and builds a
longest-prefix routing table. Each S3 operation is matched to a grant scope and
served by a per-scope `aiobotocore` client whose credentials come from
`GetDataAccess` and auto-refresh on expiry. Calls that match no grant fall
through to the default IAM client (fail-closed), and cross-scope copies are
rejected.

If the caller has no grants (or no permission to list them), `register()`
installs nothing and plain `s3fs` handles `s3://` with zero added overhead.

## Install

```bash
pip install s3fs-access-grants
# or
uv add s3fs-access-grants
```

## Usage

Registration is explicit — importing the package does no AWS I/O.

```python
import s3fs_access_grants

# Install the s3:// handler for the calling identity's grants.
s3fs_access_grants.register()

import polars as pl
df = pl.read_parquet("s3://bucket/teamA/data.parquet")  # scoped automatically
```

Pass the grants-instance account/region explicitly (e.g. in a notebook, or when
the grants instance lives in a different account than your role):

```python
import s3fs_access_grants

s3fs_access_grants.register(account_id="123456789012", region="eu-west-1")
```

`register()` is the only entry point and returns nothing — it's a one-time setup
call. It resolves the account/region, then binds them into the handler it
registers, so a later argless `fsspec.filesystem("s3")` (what pandas / polars use
under the hood) builds the filesystem with the right values. After calling it,
just use fsspec / pandas / polars as normal.

### Configuration

`register()` resolves the grants-instance account and region in this order:

| Setting    | Resolution order                                                |
| ---------- | --------------------------------------------------------------- |
| Account ID | explicit arg → `S3FS_ACCESS_GRANTS_ACCOUNT_ID` → STS caller      |
| Region     | explicit arg → `S3FS_ACCESS_GRANTS_REGION` → session default     |

The grants instance may live in a different account than the caller's role, so
the explicit arg / env is authoritative; the STS caller account is only a
same-account fallback.

### Advanced: manual construction

`register()` covers the common case. To build a scoped filesystem by hand —
e.g. pointing at a different grants account without touching the global s3://
registration — construct `ScopedS3FileSystem` directly:

```python
from s3fs_access_grants import ScopedS3FileSystem

fs = ScopedS3FileSystem(grants_account_id="123456789012", grants_region="eu-west-1")
```

## Compatibility

This subclass depends on `s3fs` internals (`_call_s3` and `_iterdir` resolving
their client via `get_s3()`). Validated against s3fs 2026.6.0 / aiobotocore
2.25.1. Re-check on any `s3fs` major bump.

## Development

```bash
bun install          # installs JS tooling + runs uv sync + lefthook install
bun run check        # lint + typecheck (ruff, ty, editorconfig)
bun run test         # pytest with coverage
bun run build        # uv build (wheel + sdist)
```

Releases are managed with [changesets](https://github.com/changesets/changesets):
add one with `bun run changeset:add`, and merging the generated "version
packages" PR bumps the version, syncs it into `pyproject.toml`, and publishes to
PyPI.

## License

MIT
