"""Offline checks for the live test's credential and process boundaries."""

import io
import os
from pathlib import Path
import sys
import subprocess
import tarfile
import tempfile
import unittest

from providers import PROVIDER, CheckFailure, provision, verify
from run import source_archive
from s3 import LocalS3
from session_test import agent_environment, run


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="asr-e2e-unit-")
        self.addCleanup(self.scratch.cleanup)
        self.path = Path(self.scratch.name) / "providers"
        self.credential = "synthetic-credential-with-quote-\"-and-backslash-\\"
        self.anthropic_base = "http://127.0.0.1:19401"
        self.openai_base = "http://127.0.0.1:19402/v1"
        self.provision(self.path, self.credential)

    def provision(self, path, credential):
        return provision(path, credential, self.anthropic_base, self.openai_base,
                         "synthetic-anthropic", 'synthetic-openai-"-\\')

    def test_credential_is_in_private_settings_for_named_local_providers(self):
        self.assertEqual(verify(self.path), self.credential)
        for file in self.path.iterdir():
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)

    def test_cloud_endpoint_override_is_rejected_for_every_agent(self):
        for filename in ("claude.json", "codex.toml", "pi.json"):
            with self.subTest(filename=filename):
                file = self.path / filename
                original = file.read_text()
                file.write_text(original.replace(self.anthropic_base if filename == "claude.json" else self.openai_base, "https://api.example.invalid"))
                with self.assertRaises((CheckFailure, ValueError)):
                    verify(self.path)
                file.write_text(original)

    def test_cloud_provider_selection_is_rejected(self):
        file = self.path / "codex.toml"
        file.write_text(file.read_text().replace(f'model_provider = "{PROVIDER}"',
                                                'model_provider = "openai"'))
        with self.assertRaisesRegex(CheckFailure, "codex_provider_not_local"):
            verify(self.path)

    def test_public_or_symlinked_settings_are_rejected(self):
        file = self.path / "pi.json"
        file.chmod(0o644)
        with self.assertRaisesRegex(CheckFailure, "provider_file_permissions"):
            verify(self.path)
        file.chmod(0o600)
        target = self.path / "private.json"
        file.rename(target)
        file.symlink_to(target)
        with self.assertRaisesRegex(CheckFailure, "provider_file_permissions"):
            verify(self.path)

    def test_agents_do_not_inherit_credentials_or_global_config(self):
        directory = Path(self.scratch.name) / "agent"
        directory.mkdir()
        environment = agent_environment(directory)
        self.assertEqual(set(environment), {"PATH", "LANG", "NO_COLOR", "HOME", "XDG_CONFIG_HOME",
                                           "XDG_DATA_HOME", "XDG_STATE_HOME", "TMPDIR"})
        self.assertNotEqual(environment["HOME"], os.environ["HOME"])

    def test_multiline_credentials_are_refused_before_writing(self):
        for credential in ("", "synthetic\nvalue", "synthetic\rvalue"):
            with self.assertRaisesRegex(CheckFailure, "invalid_proxy_credential"):
                self.provision(self.path / "bad", credential)


class HarnessTests(unittest.TestCase):
    def test_missing_key_stops_before_docker_or_model_work(self):
        environment = {key: value for key, value in os.environ.items() if key != "ASR_PROXY_KEY_FILE"}
        result = subprocess.run([sys.executable, Path(__file__).with_name("run.py")], env=environment,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn('"code": "proxy_key_file_required"', result.stderr)

    def test_process_errors_do_not_disclose_output(self):
        with self.assertRaises((CheckFailure, ValueError)) as failure:
            run([sys.executable, "-c", "import sys; print('synthetic private output'); sys.exit(7)"])
        self.assertNotIn("private output", str(failure.exception))

    def test_source_image_excludes_host_history_and_generated_directories(self):
        with tarfile.open(fileobj=io.BytesIO(source_archive()), mode="r:gz") as archive:
            names = archive.getnames()
        self.assertIn("tests/e2e/Dockerfile", names)
        self.assertIn("crates/asr-cli/src/main.rs", names)
        for name in names:
            self.assertFalse(set(Path(name).parts) & {".git", "node_modules", "target", ".venv", "__pycache__"}, name)
            self.assertFalse(Path(name).is_absolute(), name)

    def test_storage_is_limited_to_numeric_loopback(self):
        for endpoint in ("https://example.invalid", "http://localhost:9000", "http://127.0.0.1.attacker.invalid",
                         "http://synthetic:synthetic@127.0.0.1:9000", "http://127.0.0.1:9000?redirect=1"):
            with self.subTest(endpoint=endpoint), self.assertRaises((CheckFailure, ValueError)):
                LocalS3(endpoint, "synthetic", "synthetic")
        LocalS3("http://127.0.0.1:9000", "synthetic", "synthetic")


if __name__ == "__main__":
    unittest.main()
