"""Offline regressions for configurable live runners. No model process is started."""

import contextlib
import io
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import tomllib
import types
import unittest
from unittest.mock import patch

from live_provider import loopback_endpoint, private_json

ROOT = Path(__file__).resolve().parents[1]


class ProviderTests(unittest.TestCase):
    def test_explicit_ports_and_protocol_paths_are_preserved(self):
        for value in ("http://127.0.0.1:19301/v1", "https://127.0.0.1:19302/anthropic"):
            self.assertEqual(loopback_endpoint(value + "/"), value)
        for value in (None, "", "http://127.0.0.1", "http://127.0.0.1:0", "https://api.example.invalid/v1",
                      "http://localhost:19301", "http://127.0.0.1.attacker.invalid:19301",
                      "http://user:synthetic@127.0.0.1:19301", "http://127.0.0.1:19301?redirect=1",
                      "http://127.0.0.1:19301/#fragment", "http://127.0.0.1:invalid", "file:///tmp/settings"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "explicit_loopback_endpoint_required"):
                loopback_endpoint(value)

    def test_private_settings_preserve_escaped_values_and_refuse_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "provider.json"
            value = {"apiKey": 'synthetic-"-\\', "baseUrl": "http://127.0.0.1:19301/v1"}
            private_json(file, value)
            self.assertEqual(json.loads(file.read_text()), value)
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                private_json(file, {})

    def test_replay_routes_both_protocols_from_private_settings(self):
        namespace = runpy.run_path(str(ROOT / "crates/asr-cli/scripts/live_replay.py"))
        with tempfile.TemporaryDirectory() as directory:
            scratch = Path(directory)
            key = scratch / "key"
            key.write_text('synthetic-"-\\')
            report = scratch / "report.json"
            expected = {"openai": "http://127.0.0.1:19301/v1", "anthropic": "http://127.0.0.1:19302"}
            seen = []
            validate_run = subprocess.run

            def fake_run(argv, **kwargs):
                config = Path(argv[argv.index("--provider-settings") + 1])
                settings = json.loads(config.read_text())
                self.assertEqual(settings["baseUrl"], expected[settings["protocol"]])
                self.assertEqual(settings["apiKey"], key.read_text())
                self.assertEqual(config.stat().st_mode & 0o777, 0o600)
                validation = validate_run(["node", str(ROOT / "tools/validator/bin/asr-validate.js"), "--json", argv[2]],
                                          capture_output=True, text=True)
                self.assertEqual(validation.returncode, 0)
                self.assertEqual(json.loads(validation.stdout)["errors"], 0)
                self.assertEqual(json.loads(validation.stdout)["warnings"], 0)
                rows = [json.loads(line) for line in Path(argv[2]).read_text().splitlines()]
                self.assertEqual(rows[-1]["model"]["requested"], "synthetic-" + settings["protocol"])
                seen.append(config)
                return subprocess.CompletedProcess(argv, 1, b"", b"")

            argv = ["live_replay.py", "--key-file", str(key), "--out", str(report)]
            for protocol, endpoint in expected.items():
                argv += ["--" + protocol + "-base-url", endpoint, "--" + protocol + "-model", "synthetic-" + protocol]
            with patch.object(sys, "argv", argv), patch("subprocess.run", side_effect=fake_run), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(namespace["main"](), 1)
            self.assertEqual(len(seen), 2)
            self.assertTrue(all(not file.exists() for file in seen))
            self.assertNotIn(key.read_text(), report.read_text())

    def test_codex_runner_loads_custom_model_and_credential_from_private_provider(self):
        recorder = types.ModuleType("asr_codex_hooks.recorder")
        recorder.VENDOR = "org.agentsessionrecord.hooks"
        with patch.dict(sys.modules, {"asr_codex_hooks.recorder": recorder}):
            namespace = runpy.run_path(str(ROOT / "plugins/codex/scripts/live_test.py"))
        class ProbeComplete(Exception):
            pass
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = root / "key"
            credential = 'synthetic-"-\\'
            key.write_text(credential)
            seen = []
            def fake_run(argv, **kwargs):
                if argv[0] != "codex":
                    return subprocess.CompletedProcess(argv, 0, json.dumps({"hooks": {"PreToolUse": [], "PermissionRequest": []}}), "")
                config = Path(kwargs["env"]["CODEX_HOME"]) / "config.toml"
                settings = tomllib.loads(config.read_text())
                self.assertEqual(settings["model"], 'synthetic-model-"-\\')
                provider = settings["model_providers"][settings["model_provider"]]
                self.assertEqual(provider["base_url"], "http://127.0.0.1:19305/v1")
                self.assertEqual(provider["http_headers"]["Authorization"], "Bearer " + credential)
                self.assertEqual(config.stat().st_mode & 0o777, 0o600)
                self.assertNotIn(credential, kwargs["env"].values())
                seen.append(config)
                raise ProbeComplete()
            argv = ["live_test.py", str(root / "summary.json"), "--key-file", str(key), "--base-url",
                    "http://127.0.0.1:19305/v1", "--model", 'synthetic-model-"-\\']
            with patch.object(sys, "argv", argv), patch("subprocess.run", side_effect=fake_run), self.assertRaises(ProbeComplete):
                namespace["main"]()
            self.assertEqual(len(seen), 1)
            self.assertFalse(seen[0].exists())

    def test_standalone_runners_compile_without_creating_caches(self):
        for file in ("crates/asr-cli/scripts/live_replay.py", "recorders/acp/scripts/live.py",
                     "recorders/litellm/scripts/live.py", "plugins/codex/scripts/live_test.py",
                     "importers/telemetry-approvals/tools/live_test.py"):
            source = (ROOT / file).read_text()
            compile(source, file, "exec")


if __name__ == "__main__":
    unittest.main()
