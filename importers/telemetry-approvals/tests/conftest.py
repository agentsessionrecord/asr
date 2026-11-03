from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def validate_outputs(tmp_path):
    yield
    # Every ASR output, including the inputs assembled with the Python writer,
    # must pass the independent Node validator.
    for path in tmp_path.glob('*.asr.jsonl'):
        result = subprocess.run(['node', str(ROOT / 'tools/validator/bin/asr-validate.js'), '--json', str(path)], capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
