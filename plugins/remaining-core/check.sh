#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
pnpm --filter @agent-session/types build
pnpm --filter @agent-session/writer build
# Cross-core recovery tests execute the bundled Gemini and Qwen command hooks.
node plugins/gemini-qwen-core/build.mjs
node --test plugins/remaining-core/test/*.test.mjs
node plugins/remaining-core/test/samples.mjs --check
