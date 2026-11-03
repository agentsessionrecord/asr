#!/usr/bin/env python3
"""Reproduce the synthetic native export from an already patched checkout."""
import json
import os
from pathlib import Path
import shutil
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
    directory = work / ".fx/sessions/cb1PK0RGxCmY"
    directory.mkdir(parents=True)
    for source, target in [("session.json", "session.json"), ("permissions.json", "permissions.json"), ("events.native", "events.jsonl")]:
        shutil.copyfile(package / "samples/native" / source, directory / target)
    (directory / "session.lock").touch()
    environment["HOME"] = str(work)
    command = [str(checkout / "zig-out/bin/fx"), "sessions", "export", "--format", "agent-session", "--session", directory.name]
    output = work / "session.jsonl"
    with output.open("wb") as stream:
        subprocess.run(command, cwd=checkout, env=environment, stdout=stream, check=True)
    actual = [json.loads(line) for line in output.read_text().splitlines()]
    expected = [json.loads(line) for line in (package / "samples/asr/session.jsonl").read_text().splitlines()]
    if actual != expected:
        raise SystemExit("native export differs from the packaged sample")
    subprocess.run(["node", "tools/validator/bin/asr-validate.js", "--summary", str(output)], cwd=repository, check=True)
    print(f"{package.name}: native fixture reproduction passed")
