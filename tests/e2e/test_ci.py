"""Exercise the optional CI section without starting Docker or model processes."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class CITests(unittest.TestCase):
    def exercise(self, enabled=False, fail=False):
        with tempfile.TemporaryDirectory(prefix="asr-e2e-ci-") as temporary:
            directory = Path(temporary)
            (directory / "scripts").mkdir()
            (directory / "tests/e2e").mkdir(parents=True)
            (directory / "bin").mkdir()
            shutil.copyfile(ROOT / "scripts/ci.sh", directory / "scripts/ci.sh")
            for name in ("run.py", "test_harness.py"):
                (directory / "tests/e2e" / name).touch()
            for name in ("node", "python3", "git"):
                stub = directory / "bin" / name
                stub.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$ASR_E2E_CI_LOG"\n'
                                'if [ "$*" = "tests/e2e/run.py" ] && [ "$ASR_E2E_CI_FAIL" = 1 ]; '
                                'then exit 23; fi\n')
                stub.chmod(0o755)
            log = directory / "commands"
            environment = {**os.environ, "PATH": str(directory / "bin") + ":" + os.environ["PATH"],
                           "ASR_TEST_E2E": "1" if enabled else "0", "ASR_E2E_CI_FAIL": "1" if fail else "0",
                           "ASR_E2E_CI_LOG": str(log)}
            result = subprocess.run(["bash", directory / "scripts/ci.sh"], cwd=directory,
                                    env=environment, capture_output=True, text=True, timeout=10)
            return result, log.read_text().splitlines()

    def test_default_runs_offline_checks_and_skips_live_suite(self):
        result, commands = self.exercise()
        self.assertEqual(result.returncode, 0)
        self.assertIn("-m unittest discover -s tests/e2e -p test_*.py", commands)
        self.assertNotIn("tests/e2e/run.py", commands)
        self.assertRegex(result.stdout, r"Container end-to-end\s+\| SKIP")

    def test_opt_in_runs_live_suite_once(self):
        result, commands = self.exercise(enabled=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(commands.count("tests/e2e/run.py"), 1)
        self.assertRegex(result.stdout, r"Container end-to-end\s+\| PASS")

    def test_live_failure_reaches_ci_result_and_later_checks_still_run(self):
        result, commands = self.exercise(enabled=True, fail=True)
        self.assertEqual(result.returncode, 1)
        self.assertRegex(result.stdout, r"Container end-to-end\s+\| FAIL\s+\| exit 23")
        self.assertIn("scripts/check-privacy.mjs", commands)


if __name__ == "__main__":
    unittest.main()
