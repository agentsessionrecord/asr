#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."
python3 crates/asr-core/generate.py --check
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
python3 -m unittest discover -s crates/asr-convert/scripts -p 'test_*.py'
node tools/validator/bin/asr-validate.js --summary crates/asr-convert/tests/golden
