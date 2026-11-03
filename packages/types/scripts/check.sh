#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../../.."
export PATH="$HOME/.local/go/bin:$PATH"
python3 packages/types/scripts/generate.py --check
pnpm --filter @agent-session/types test
pnpm --filter @agent-session/writer test
uv run --package agent-session-record pytest python/agent_session_record/tests
(cd go && go test ./...)
if [[ -n "$(gofmt -l go/asr)" ]]; then
  echo "Go sources need gofmt" >&2
  exit 1
fi
