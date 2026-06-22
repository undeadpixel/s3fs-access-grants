#!/usr/bin/env node

/**
 * CI-only script: runs `changeset version` then syncs the resulting
 * package.json version into pyproject.toml and uv.lock.
 */

import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";

if (!process.env.CI) {
  console.error(
    "This script is intended for CI only. Set CI=true to override.",
  );
  process.exit(1);
}

// 1. Run changeset version (bumps package.json + writes CHANGELOG.md)
execFileSync("bunx", ["changeset", "version"], { stdio: "inherit" });

// 2. Read the new version from package.json
const { version } = JSON.parse(readFileSync("package.json", "utf-8"));
console.log(`Syncing version ${version} to pyproject.toml and uv.lock`);

// 3. Update pyproject.toml and uv.lock. Resolution is incremental — without
//    --upgrade, transitive pins are preserved and only the local project's
//    entry is rewritten.
execFileSync("uv", ["version", version], { stdio: "inherit" });
