import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = ROOT / "tools/validator/bin/asr-validate.js"


@pytest.fixture(autouse=True)
def validate_written_streams(tmp_path):
    yield
    for path in tmp_path.rglob("*.jsonl"):
        result = subprocess.run(["node", str(VALIDATOR), "--json", "--summary", str(path)], capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        report = json.loads(result.stdout)
        assert report["errors"] == 0, report
        assert report["warnings"] == 0, report
