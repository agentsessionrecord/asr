#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export PATH="$PATH:$HOME/.local/go/bin"
files=$(gofmt -l go/asr)
if [[ -n $files ]]; then
  printf '%s\n' "$files" >&2
  exit 1
fi
