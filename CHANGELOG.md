# s3fs-access-grants

## 0.2.1

### Patch Changes

- 1d4006c: Use a placeholder AWS account ID (`123456789012`) in the README and module
  docstring examples instead of a real account number.

## 0.2.0

### Minor Changes

- f497575: First version: transparent S3 Access Grants for fsspec/s3fs. Call `register()`
  once and every fsspec consumer (pandas, polars, universal-pathlib, `fsspec.open`)
  routes each `s3://` call through a credential scoped to the matching grant, with
  no Access Grants logic in application code.

### Patch Changes

- bfa95f3: Widen dependency bounds: `s3fs`/`fsspec` to `>=2026,<2027`, `boto3` to
  `>=1.34,<2`. Add `aiobotocore>=2.22,<4` as a direct dependency (it is imported
  directly) and drop the unused `aioboto3`.
- 72648d6: Fix `register()` breaking URL-based reads (e.g. `pandas.read_json("s3://...")`).
  It registered a `functools.partial`, but fsspec resolves `s3://` URLs by calling
  classmethods (`_get_kwargs_from_urls`, `_strip_protocol`, ...) on the registered
  object, which a partial lacks. Register a dynamically-created `ScopedS3FileSystem`
  subclass instead, with the resolved account/region as class-level defaults.
