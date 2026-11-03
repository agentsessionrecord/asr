#!/usr/bin/env python3
"""Reproduce the synthetic native export from an already patched checkout."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile

package = Path(__file__).resolve().parent
repository = package.parent.parent
if len(sys.argv) != 2:
    raise SystemExit("usage: reproduce.py PATCHED_CHECKOUT")
checkout = Path(sys.argv[1]).resolve()

def make_database(path, fixture):
    with sqlite3.connect(path) as database:
        database.executescript((package / "samples/native" / fixture).read_text())

with tempfile.TemporaryDirectory(prefix="asr-native-fixture-") as temporary:
    work = Path(temporary)
    environment = os.environ.copy()
    directory = work / "synthetic-session"
    directory.mkdir()
    make_database(directory / "inbound.db", "in.sql")
    make_database(directory / "outbound.db", "out.sql")
    command = ["pnpm", "exec", "tsx", ".claude/skills/export-agent-session/scripts/export-agent-session.ts", "--session", directory.name, "--directory", str(directory), "--format", "agent-session"]
    output = work / "session.jsonl"
    with output.open("wb") as stream:
        subprocess.run(command, cwd=checkout, env=environment, stdout=stream, check=True)
    actual = [json.loads(line) for line in output.read_text().splitlines()]
    expected = [json.loads(line) for line in (package / "samples/asr/session.jsonl").read_text().splitlines()]
    if actual != expected:
        raise SystemExit("native export differs from the packaged sample")
    subprocess.run(["node", "tools/validator/bin/asr-validate.js", "--summary", str(output)], cwd=repository, check=True)
    print(f"{package.name}: native fixture reproduction passed")
