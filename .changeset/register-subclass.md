---
"s3fs-access-grants": patch
---

Fix `register()` breaking URL-based reads (e.g. `pandas.read_json("s3://...")`).
It registered a `functools.partial`, but fsspec resolves `s3://` URLs by calling
classmethods (`_get_kwargs_from_urls`, `_strip_protocol`, ...) on the registered
object, which a partial lacks. Register a dynamically-created `ScopedS3FileSystem`
subclass instead, with the resolved account/region as class-level defaults.
