#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."
pnpm exec tsc -p exporters/git-notes/tsconfig.json
node --experimental-strip-types --disable-warning=ExperimentalWarning --test exporters/git-notes/test/*.test.mjs apps/gitlab/test/*.test.mjs
