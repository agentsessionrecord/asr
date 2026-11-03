#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/plugin"
node --input-type=module -e 'const [major, minor] = process.versions.node.split(".").map(Number); if (major < 24 || (major === 24 && minor < 15)) throw new Error("DeepSeek plugin checks require Node 24.15 or newer")'
npm ci --ignore-scripts
npm run build
npm run lint
npm run typecheck
npm test
npm audit --omit=dev
node ../pack-smoke.mjs
