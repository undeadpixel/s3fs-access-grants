---
"s3fs-access-grants": patch
---

Guard `register()` against missing AWS access. When credentials, region, or
connectivity are unavailable (no profile/role/env, unreachable endpoint),
`register()` now fails open and leaves the default `s3fs` in place instead of
raising, so it is safe to call unconditionally in tests and CI.
