"""Validate every ASR artifact produced by these tests with the Node validator."""
from pathlib import Path
import subprocess

import pytest

from asr_importer_core import Stream

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def validate_written_streams(monkeypatch):
    original = Stream.write

    def write(self, output):
        original(self, output)
        result = subprocess.run(["node", str(ROOT / "tools/validator/bin/asr-validate.js"), str(output)], capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr

    monkeypatch.setattr(Stream, "write", write)
