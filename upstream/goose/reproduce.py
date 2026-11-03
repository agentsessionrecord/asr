#!/usr/bin/env python3
"""Reproduce the synthetic export from the patched native Rust code."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

package = Path(__file__).resolve().parent
repository = package.parent.parent
if len(sys.argv) != 2:
    raise SystemExit("usage: reproduce.py PATCHED_CHECKOUT")
checkout = Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory(prefix="asr-native-fixture-") as temporary:
    work = Path(temporary)
    environment = os.environ.copy()
    output = work / "session.jsonl"
    environment["ASR_TEST_OUTPUT"] = str(output)
    command = ["cargo", "test", "-q", "-p", "goose", "--test", "agent_session_export", "fixture_export_for_external_validation"]
    subprocess.run(command, cwd=checkout, env=environment, check=True)
    actual = [json.loads(line) for line in output.read_text().splitlines()]
    expected = [json.loads(line) for line in (package / "samples/asr/session.jsonl").read_text().splitlines()]
    if actual != expected:
        raise SystemExit("native export differs from the packaged sample")
    subprocess.run(["node", "tools/validator/bin/asr-validate.js", "--summary", str(output)], cwd=repository, check=True)
    print(f"{package.name}: native fixture reproduction passed")
