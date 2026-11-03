#!/usr/bin/env python3
"""Run the shared passive JSON-hook recorder."""

import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True

# No payload, traceback or decision may escape into the hook protocol.
try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks-core"))
    from observer import main
    event = sys.argv[1] if len(sys.argv) == 2 else None
    code = main("lingma", event)
except BaseException:
    code = 0
os._exit(code)
