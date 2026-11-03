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
    source = work / "sessions/2026/10/31"
    source.mkdir(parents=True)
    (source / "rollout-2026-10-31T12-00-00-019a3c2e-7b1f-7d40-9e2a-5c8b1d3f6e70.jsonl").write_bytes((package / "samples/native/session.jsonl").read_bytes())
    command = ["cargo", "run", "-q", "-p", "codex-session-export", "--example", "export", "--", "export", "--session", "019a3c2e-7b1f-7d40-9e2a-5c8b1d3f6e70", "--codex-home", str(work)]
    with output.open("wb") as stream:
        subprocess.run(command, cwd=checkout / "codex-rs", env=environment, stdout=stream, check=True)
    actual = [json.loads(line) for line in output.read_text().splitlines()]
    expected = [json.loads(line) for line in (package / "samples/asr/session.jsonl").read_text().splitlines()]
    if actual != expected:
        raise SystemExit("native export differs from the packaged sample")
    subprocess.run(["node", "tools/validator/bin/asr-validate.js", "--summary", str(output)], cwd=repository, check=True)
    print(f"{package.name}: native fixture reproduction passed")
