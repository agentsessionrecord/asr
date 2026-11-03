#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
pnpm --filter @agent-session/types build
pnpm --filter @agent-session/writer build
pnpm --dir plugins/opencode build
pnpm --dir plugins/opencode test
