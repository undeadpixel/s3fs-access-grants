# Changesets

This folder is managed by [@changesets/cli](https://github.com/changesets/changesets).

It holds `.md` changeset files — each one describes a change that should appear in the changelog and bump the package version. Add a new changeset with:

```bash
bun run changeset:add
```

Changeset files are consumed when `changeset version` runs (in CI) — they update `CHANGELOG.md`, bump `package.json` version, sync that version into `pyproject.toml`/`uv.lock`, and are then deleted.
