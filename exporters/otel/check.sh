#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
cd -- "$root"
PYTHONPATH="$root/exporters/otel/src${PYTHONPATH:+:$PYTHONPATH}" python3 -m unittest discover -s exporters/otel/tests -v
