"""Create a deterministic ASR sample from the synthetic hook fixture."""
from pathlib import Path
import shutil
import sys
import tempfile

from asr_codex_hooks.recorder import record


def main():
    fixture = Path(__file__).resolve().parents[1] / "fixtures/hooks.jsonl"
    with tempfile.TemporaryDirectory(prefix="asr-codex-fixture-") as temporary:
        output = Path(temporary) / "asr"
        for line in fixture.read_bytes().splitlines():
            if not record(line, output, full=True, receipt="2026-11-01T12:00:00.000000Z"):
                raise RuntimeError("Synthetic capture failed")
        shutil.copyfile(next(output.glob("*.jsonl")), Path(sys.argv[1]))


if __name__ == "__main__":
    main()
