#!/usr/bin/env python3
"""Run the shared passive JSON-hook recorder."""

import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True

# The native PreToolUse contract requires a decision. Its "allow" value
# delegates to later hooks and default policy. Emit the fixed neutral response
# before capture so a recorder deadline cannot leave an invalid response.
responses = {"PreToolUse": b'{"decision":"allow"}\n',
             "Stop": b'{"decision":""}\n'}
try:
    os.write(1, responses.get(sys.argv[1] if len(sys.argv) == 2 else None, b'{}\n'))
except BaseException:
    os._exit(0)

# No payload or traceback may escape into the hook protocol.
try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks-core"))
    from observer import main
    event = sys.argv[1] if len(sys.argv) == 2 else None
    code = main("antigravity", event)
except BaseException:
    code = 0
os._exit(code)
