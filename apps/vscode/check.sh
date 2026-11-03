#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
cd -- "$root"
cargo build -p asr-cli --locked
pnpm --dir apps/vscode run typecheck
pnpm --dir apps/vscode run build
pnpm --dir apps/vscode run test:unit
if [[ -n ${DISPLAY:-} ]]; then
  pnpm --dir apps/vscode run test:harness
else
  xvfb-run -a pnpm --dir apps/vscode run test:harness
fi
