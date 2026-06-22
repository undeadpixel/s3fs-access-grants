---
"s3fs-access-grants": patch
---

Widen dependency bounds: `s3fs`/`fsspec` to `>=2026,<2027`, `boto3` to
`>=1.34,<2`. Add `aiobotocore>=2.22,<4` as a direct dependency (it is imported
directly) and drop the unused `aioboto3`.
