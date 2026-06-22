# AGENTS.md

> Instructions for AI coding assistants working on this project.
>
> **Note**: `CLAUDE.md` is a symlink to this file. Edit `AGENTS.md`; both reflect the change.

## Purpose

`s3fs-access-grants` is a published library that makes [S3 Access Grants](https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-grants.html)
transparent to [fsspec](https://filesystem-spec.readthedocs.io/) / [s3fs](https://s3fs.readthedocs.io/).
`register()` installs `ScopedS3FileSystem` for `s3://`; every fsspec consumer
(pandas, polars, universal-pathlib, `fsspec.open`) then routes each call through
a credential scoped to the matching grant.

All code lives in `src/s3fs_access_grants/`:

- `__init__.py` — public API. Exposes exactly three names: `register()` (the only
  entry point — records account/region overrides, registers the handler, returns
  the live filesystem), `ScopedS3FileSystem` (for advanced/manual construction),
  and `CrossScopeCopyError`. **No AWS I/O on import** — registration is explicit.
- `filesystem.py` — everything else: `ScopedS3FileSystem` (the s3fs subclass),
  grant enumeration + longest-prefix routing, per-scope auto-refreshing clients,
  and the cross-scope copy guard. The `resolve_account_id` / `resolve_region` /
  `set_overrides` / `enumerate_scopes` helpers are module-internal (not in
  `__all__`, not re-exported) — `register()` and the FS constructor share them.

See [README.md](./README.md) for end-to-end behaviour.

## Tech stack

- Python 3.11+ (dev interpreter pinned to 3.14 via `.python-version`)
- uv (package + venv management), bun (task runner + changesets/lefthook tooling)
- boto3 / aiobotocore (AWS), s3fs + fsspec (filesystem layer)
- ruff (lint + format), ty (type check), pytest (test)
- hatchling (build backend), changesets (release/version management)

## Essential commands

Use `bun` commands, not raw tool invocations:

```bash
bun install          # uv sync + lefthook install
bun run check        # lefthook pre-commit on all files (ruff, ty, editorconfig)
bun run test         # pytest with inline coverage (term-missing)
bun run build        # uv build (wheel + sdist)
uv run pytest tests/test_filesystem.py   # single test file
uv build && uvx twine check dist/*       # verify the package is publishable
```

`bun run check` runs lefthook's `pre-commit`, whose per-tool globs operate on
`{staged_files}`. **Stage your changes (`git add -A`) before running it** — new,
unstaged files are invisible to ruff/ty/editorconfig and produce a false-green
that pre-commit will reject at commit time.

## Development workflow

1. **Read** the existing code in `filesystem.py` before changing it. Match the
   style you find there.
2. **Implement** the smallest change that does the job. No abstractions for
   hypothetical future needs.
3. **Test** — add/adjust tests, run `bun run test`.
4. **Verify** — `git add -A`, then `bun run check` → `bun run test`. Fix every
   issue.
5. **Changeset** — for any user-facing change, `bun run changeset:add` (`patch`
   for fixes, `minor` for features, `major` for breaking). The summary becomes
   the CHANGELOG entry. Pure chore/CI changes skip this.

## Python conventions

### Style and typing

- Modern syntax only: `str | None` not `Optional`; `list[str]`/`dict[str, X]`
  not `List`/`Dict`; f-strings not `%`/`.format()`.
- Annotate every function's parameters and return type. Return concrete types
  (`list[X]`), accept abstract ones (`Sequence[X]`) only where it broadens usable
  input.
- Module-level logger: `logger = logging.getLogger(__name__)`. Use `%s`/`%r`
  formatting in log calls, not f-strings, so formatting is deferred.
- Google-style docstrings on public functions/classes/methods. First line is an
  imperative summary of *what*, not *how*. Skip `Args`/`Returns` that merely echo
  the signature. `_`-prefixed helpers get a one-liner at most. No docstrings in
  test bodies (file-level only).
- Imports at the top of the file, always.

### Error handling

- Hard-fail: raise, don't return error dicts or result objects.
- Catch specific exception types, not bare `except`. Use `raise ... from e` to
  preserve the chain. Broad suppression is confined to one place: the
  best-effort teardown in `_close_scopes` uses `contextlib.suppress(Exception)`
  so a failing client close can't abort the rest of the cleanup.

### Tooling compliance

- `ruff` and `ty` must both pass with zero warnings before commit.

### Documented exceptions (this is a library on top of s3fs internals)

The general rule is **no suppressions and no `Any`** — fix the underlying issue.
This project has a few unavoidable, deliberate exceptions, each carrying an
inline comment explaining why. Do not remove them, and match the pattern if you
add genuinely analogous code:

- **`# noqa: SLF001`** on the calls into `S3FileSystem._call_s3` / `_iterdir` and
  on `session._credentials`. The entire design is driving s3fs/aiobotocore
  internals; the docstring at the top of `filesystem.py` documents the seam.
- **`# ty: ignore[invalid-argument-type]`** on the `_ClientOverride(...)`
  arguments. The proxy is a structural stand-in for the filesystem; ty can't see
  the duck-typing.
- **`Any`** for the per-scope client dict — aiobotocore clients are untyped.
- **Module-level mutable globals** (`_SCOPE_CACHE`, `_OVERRIDE_*`) — the routing
  table and `register()` overrides are intentionally process-wide; this is the one
  place module-level mutable state is allowed.

Anything beyond these requires a comment justifying it. Don't reach for a new
suppression to make a check pass — fix the code first.

### Compatibility seam

`ScopedS3FileSystem` depends on `s3fs` internals (`_call_s3` and `_iterdir`
resolving their client via `get_s3()`). The module docstring records the exact
versions it was validated against. **On any `s3fs` bump, re-verify that seam**
and update the docstring + the README compatibility note.

## Testing

- Mirror `src/` layout under `tests/`.
- Prefer inline data and pure-logic tests. The routing logic (`_parse_grant`,
  `_scope_for`, longest-prefix ordering) is testable without AWS — keep it that
  way; use a `SimpleNamespace` stand-in rather than constructing a real
  filesystem (which makes live AWS calls).
- Mock external services (boto3/aiobotocore); never hit real AWS in tests.
- Naming: `test_{behavior}` inside `class Test{Unit}:`. Plain `assert`,
  `pytest.raises` for exceptions. One behavior per test. `_make_{object}()` for
  builders.

## Non-negotiable rules

- **Use `bun` commands** for check/test/build — not raw tool invocations.
- **Conventional commits** (commitlint-enforced): `feat:`, `fix:`, `docs:`,
  `refactor:`, `test:`, `chore:`.
- **No secrets committed**: never commit `.env`, API keys, AWS credentials, or
  account-specific connection strings.
- **No AI authorship anywhere**: in commit messages, PRs, or any text, never
  refer to yourself as an assistant / Claude / AI, and never add "generated by"
  or "co-authored by AI" lines. Write as a human developer would.
- **Releases go through changesets**: never hand-edit the version in
  `pyproject.toml` / `package.json`. CI bumps it from changeset files via
  `scripts/ci-bump-versions.js` and publishes to PyPI.
