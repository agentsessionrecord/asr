"""Check reproducibility and schema-driven drift detection in an isolated tree."""
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]


def test_generation_is_reproducible_and_stale_schema_changes_fail(tmp_path):
    for relative in ("schema/v0", "packages/types/scripts"):
        shutil.copytree(ROOT / relative, tmp_path / relative)
    script = tmp_path / "packages/types/scripts/generate.py"
    command = [sys.executable, str(script)]
    subprocess.run(command, check=True, capture_output=True)
    subprocess.run([*command, "--check"], check=True, capture_output=True)
    source = tmp_path / "schema/v0/discovery.schema.json"
    source.write_text(source.read_text().replace('"title":', '"description": "Synthetic schema change", "title":', 1))
    result = subprocess.run([*command, "--check"], capture_output=True, text=True)
    assert result.returncode == 1
    for name in ("packages/types/src/index.ts", "agent_session_record/models.py", "go/asr/types_generated.go", "_schemas/discovery.schema.json"):
        assert name in result.stderr
    subprocess.run(command, check=True, capture_output=True)
    subprocess.run([*command, "--check"], check=True, capture_output=True)
