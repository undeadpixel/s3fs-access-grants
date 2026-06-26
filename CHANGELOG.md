# s3fs-access-grants

## 0.1.1

### Patch Changes

- 9656e1d: Guard `register()` against missing AWS access. When credentials, region, or
  connectivity are unavailable (no profile/role/env, unreachable endpoint),
  `register()` now fails open and leaves the default `s3fs` in place instead of
  raising, so it is safe to call unconditionally in tests and CI.

## 0.1.0

### Minor Changes

- c6c0617: First release: transparent S3 Access Grants for fsspec/s3fs. Call `register()`
  once and every fsspec consumer (pandas, polars, universal-pathlib, `fsspec.open`)
  routes each `s3://` call through a credential scoped to the matching grant, with
  no Access Grants logic in application code.
