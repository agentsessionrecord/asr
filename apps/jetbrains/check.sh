#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
cd -- "$root"
cargo build -p asr-cli --locked
pnpm --dir apps/viewer run build
cd -- apps/jetbrains
./gradlew --project-cache-dir ../../target/jetbrains-gradle --no-daemon test buildPlugin
