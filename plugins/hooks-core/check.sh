#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."
python3 -I -S -B -m unittest discover -s plugins/hooks-core/tests -p 'test_*.py'
