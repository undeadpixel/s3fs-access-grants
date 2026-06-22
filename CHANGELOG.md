# s3fs-access-grants

## 0.1.0

### Minor Changes

- c6c0617: First release: transparent S3 Access Grants for fsspec/s3fs. Call `register()`
  once and every fsspec consumer (pandas, polars, universal-pathlib, `fsspec.open`)
  routes each `s3://` call through a credential scoped to the matching grant, with
  no Access Grants logic in application code.
