"""Official-contract fixtures for eight additional passive hook adapters."""

import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

CORE = Path(__file__).resolve().parents[1]
ROOT = CORE.parents[1]
sys.path.insert(0, str(CORE))
from adapters import load, normalize
from install import merge_native, registrations
import observer
from projection import HOOK, META, filename
from storage import encode

AGENTS = ("devin", "kiro", "junie", "lingma", "firebender", "antigravity", "auggie", "tabnine")
TOTAL = {"files": 0, "records": 0, "errors": 0, "warnings": {}}
SESSION = "synthetic-session"


def fixtures(agent):
    return json.loads((CORE.parent / agent / "fixtures/hooks.json").read_text())


def response(agent, native):
    if agent == "antigravity":
        return {"PreToolUse": b'{"decision":"allow"}\n', "Stop": b'{"decision":""}\n'}.get(native, b'{}\n')
    return b""


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="asr-adapters-b-")
        self.root = Path(self.temp.name)
        self.out = self.root / "captures"
        self.out.mkdir(mode=0o700)

    def tearDown(self):
        try:
            for path in self.out.rglob("*.jsonl"):
                result = subprocess.run(["node", str(ROOT / "tools/validator/bin/asr-validate.js"),
                                         "--json", "--summary", str(path)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                report = json.loads(result.stdout)
                self.assertEqual(report["errors"], 0)
                TOTAL["files"] += 1
                TOTAL["records"] += report["records"]
                for code, count in report["counts"].items():
                    TOTAL["warnings"][code] = TOTAL["warnings"].get(code, 0) + count
        finally:
            self.temp.cleanup()

    def dispatch(self, agent, entry, mode="full"):
        with mock.patch.dict(os.environ, {"ASR_OUTPUT_DIR": str(self.out), "ASR_CONTENT": mode}), \
                mock.patch.object(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(encode(entry["payload"])))), \
                mock.patch("signal.signal"), mock.patch("signal.setitimer"):
            self.assertEqual(observer.main(agent, entry["event"]), 0)

    def rows(self, agent, session=SESSION):
        path = self.out / agent / (filename(session) + ".jsonl")
        return [json.loads(line) for line in path.read_bytes().splitlines()] if path.exists() else []

    def play(self, agent, mode="full"):
        for entry in fixtures(agent):
            self.dispatch(agent, entry, mode)
        return self.rows(agent)

    def test_every_registered_event_has_a_native_fixture_and_validates_in_both_modes(self):
        for mode in ("metadata", "full"):
            for agent in AGENTS:
                with self.subTest(mode=mode, agent=agent):
                    self.assertEqual(set(load(agent)["events"]), {e["event"] for e in fixtures(agent)})
                    session = mode + "-" + agent
                    entries = copy.deepcopy(fixtures(agent))
                    key = "conversationId" if agent == "antigravity" else "conversation_id" if agent in {
                        "firebender", "auggie"} else "session_id"
                    expected = 0
                    for entry in entries:
                        if key in entry["payload"]:
                            entry["payload"][key] = session
                            expected += 1
                        if "agent_id" in entry["payload"]:
                            entry["payload"]["agent_id"] = mode + "-child"
                        self.dispatch(agent, entry, mode)
                    rows = self.rows(agent, session)
                    self.assertEqual(rows[0]["sessionId"], session)
                    self.assertEqual(rows[0]["producer"]["method"], "recorder")
                    self.assertEqual(rows[0]["agent"]["name"], agent)
                    child = self.rows(agent, mode + "-child") if agent == "firebender" else []
                    self.assertEqual(sum(r["type"] == HOOK for r in rows + child), expected)
                    self.assertEqual(len({r["id"] for r in rows}), len(rows))
                    self.assertFalse(any(r["type"] in {"approval", "inference", "file_change", "vcs"} for r in rows))
                    self.assertIn("approvals", rows[0]["missing"])
                    if agent in {"firebender", "lingma"}:
                        self.assertNotIn("startedAt", rows[0])
                        self.assertNotIn("cwd", rows[0])
                    else:
                        self.assertEqual(rows[0]["startedAt"], rows[0]["ts"])
                    ended = any("endedAt" in r for r in rows)
                    self.assertEqual(ended, agent not in {"junie", "lingma", "antigravity"})

    def test_effective_input_and_status_follow_each_documented_source(self):
        for agent in ("devin", "kiro", "lingma", "firebender", "antigravity", "auggie"):
            rows = self.play(agent)
            calls = [r for r in rows if r["type"] == "tool_call"]
            results = [r for r in rows if r["type"] == "tool_result"]
            self.assertTrue(calls)
            self.assertTrue(results)
            self.assertNotIn("input", calls[0])
            self.assertNotIn("inputText", calls[0])
            self.assertIn("requestedInput", calls[0]["_meta"][META])
            field = "CommandLine" if agent == "antigravity" else "command"
            self.assertEqual(results[0]["input"][field], "printf effective")
            self.assertNotIn("content", results[0])
            self.assertEqual(results[0]["status"], "unknown" if agent == "kiro" else "completed")
            if agent == "firebender":
                self.assertEqual(results[0]["callId"], "synthetic-call")
                self.assertEqual(results[0]["durationMs"], 0)
                self.assertEqual(len(calls), 1)
                self.assertEqual(len(results), 1)
            else:
                self.assertTrue(all("callId" not in r for r in results))
            if agent in {"devin", "lingma", "antigravity", "auggie"}:
                self.assertEqual(results[-1]["status"], "failed")
                self.assertTrue(results[-1]["error"]["message"])

    def test_unstated_status_never_becomes_success_or_denial_from_output_text(self):
        for agent in ("devin", "auggie", "antigravity", "tabnine", "kiro"):
            entry = next(copy.deepcopy(e) for e in fixtures(agent)
                         if e["event"] in {"PostToolUse", "AfterTool"})
            payload = entry["payload"]
            payload.pop("error", None)
            payload.pop("tool_error", None)
            payload.pop("tool_is_error", None)
            payload["tool_response"] = {"success": "true", "error": None, "llmContent": "denied exit 0"}
            self.dispatch(agent, entry)
            result = next(r for r in self.rows(agent) if r["type"] == "tool_result")
            self.assertEqual(result["status"], "unknown")
            self.assertNotIn("exitCode", result.get("exec", {}))
            self.assertFalse(any(r["type"] == "approval" for r in self.rows(agent)))

    def test_tabnine_original_input_and_display_do_not_become_effective_data(self):
        rows = self.play("tabnine")
        result = next(r for r in rows if r["type"] == "tool_result")
        self.assertNotIn("input", result)
        self.assertNotIn("inputText", result)
        self.assertNotIn("exec", result)
        self.assertEqual(result["content"], [{"type": "text", "text": "effective\n"}])
        self.assertNotIn("SYNTHETIC DISPLAY ONLY", json.dumps(rows))
        hook = next(r for r in rows if r["type"] == HOOK and r["_meta"][META]["event"] == "AfterTool")
        self.assertEqual(hook["_meta"][META]["originalToolInput"], {"command": "printf requested"})
        messages = [r for r in rows if r["type"] == "message"]
        self.assertEqual(messages[-1]["content"], [{"type": "text", "text": "Synthetic reply."}])
        self.assertNotEqual(rows[0]["ts"], "2026-11-01T12:00:00Z")

    def test_tabnine_text_parts_map_exactly_and_unknown_provider_shapes_are_omitted(self):
        entry = next(copy.deepcopy(e) for e in fixtures("tabnine") if e["event"] == "AfterTool")
        for index, value in enumerate(([{"text": "one\n"}, {"text": " two"}], {"parts": [{"thoughtSignature": "synthetic-opaque"}]})):
            entry["payload"]["session_id"] = "parts-" + str(index)
            entry["payload"]["tool_response"] = {"llmContent": value}
            self.dispatch("tabnine", entry)
            rows = self.rows("tabnine", "parts-" + str(index))
            result = next(r for r in rows if r["type"] == "tool_result")
            if index == 0:
                self.assertEqual(result["content"], [{"type": "text", "text": "one\n"}, {"type": "text", "text": " two"}])
            else:
                self.assertNotIn("content", result)
                self.assertNotIn("synthetic-opaque", json.dumps(rows))

    def test_permission_callbacks_stay_observations_without_invented_decisions(self):
        for agent in ("devin", "junie"):
            entry = next(copy.deepcopy(e) for e in fixtures(agent) if e["event"] == "PermissionRequest")
            entry["payload"]["session_id"] = SESSION
            self.dispatch(agent, entry)
            rows = self.rows(agent)
            self.assertFalse(any(r["type"] == "approval" for r in rows))
            hook = next(r for r in rows if r["type"] == HOOK)
            self.assertEqual(hook["_meta"][META]["tool_name"], "Bash" if agent == "junie" else "exec")

    def test_junie_sessionless_events_are_skipped_even_after_an_identified_session(self):
        rows = self.play("junie")
        self.assertEqual(sum(r["type"] == HOOK for r in rows), 2)
        self.assertEqual({r["_meta"][META]["event"] for r in rows if r["type"] == HOOK},
                         {"SessionStart", "UserPromptSubmit"})
        self.assertFalse(any(r["type"] == "tool_call" or "endedAt" in r for r in rows))
        self.assertIn("sessionless_callbacks", rows[0]["missing"])

    def test_unrecognized_ids_and_fields_cannot_invent_pairs_or_authorship(self):
        for agent in AGENTS:
            if agent in {"junie", "firebender"}:
                continue
            entry = next(copy.deepcopy(e) for e in fixtures(agent) if e["event"] in {"PreToolUse", "BeforeTool"})
            entry["payload"].update(tool_use_id="synthetic-spoof", user_email="synthetic@example.invalid",
                                    permissionDecision="deny", account_id="synthetic-account")
            self.dispatch(agent, entry)
            rows = self.rows(agent)
            call = next(r for r in rows if r["type"] == "tool_call")
            self.assertTrue(call["callId"].startswith("unlinked-call-"))
            self.assertNotIn("synthetic-spoof", json.dumps(rows))
            self.assertNotIn("synthetic@example.invalid", json.dumps(rows))
            self.assertNotIn("user", rows[0])

    def test_all_recorders_keep_metadata_mode_content_private(self):
        for agent in AGENTS:
            rows = self.play(agent, "metadata")
            text = json.dumps(rows)
            for value in ("printf requested", "printf effective", "Run the synthetic check.",
                          "/work/synthetic", "Synthetic submission.", "Synthetic reply."):
                self.assertNotIn(value, text)
            self.assertIn("content", rows[0]["missing"])

    def test_known_secrets_never_reach_extra_metadata_or_effective_input(self):
        sentinel = "SYNTHETIC_PRIVATE_VALUE_DO_NOT_SAVE"
        with mock.patch.dict(os.environ, {"SYNTHETIC_API_TOKEN": sentinel}):
            for agent in AGENTS:
                entry = next(copy.deepcopy(e) for e in fixtures(agent) if e["event"] in {"PreToolUse", "preToolUse", "BeforeTool"})
                entry["payload"]["session_id"] = SESSION if agent == "junie" else entry["payload"].get("session_id", SESSION)
                if agent == "antigravity":
                    entry["payload"]["toolCall"]["args"] = {"command": sentinel, "api_key": "synthetic-key"}
                else:
                    entry["payload"]["tool_input"] = {"command": sentinel, "api_key": "synthetic-key"}
                self.dispatch(agent, entry)
                rows = self.rows(agent)
                self.assertTrue(rows)
                self.assertNotIn(sentinel, json.dumps(rows))
                self.assertNotIn("synthetic-key", json.dumps(rows))
                self.assertTrue(any("redacted_content" in r.get("missing", []) for r in rows))

    def test_secret_interaction_answers_are_excluded_from_extra_observations(self):
        for agent, tool, native in (("antigravity", "ask_question", "PostToolUse"), ("tabnine", "ask_user", "AfterTool")):
            entry = next(copy.deepcopy(e) for e in fixtures(agent) if e["event"] == native)
            if agent == "antigravity":
                entry["payload"]["toolCall"] = {"name": tool, "args": {"answer": "synthetic-private-answer"}}
            else:
                entry["payload"].update(tool_name=tool, tool_input={"answer": "synthetic-private-answer"},
                                        tool_response={"llmContent": "synthetic-private-answer"})
            self.dispatch(agent, entry)
            rows = self.rows(agent)
            self.assertNotIn("synthetic-private-answer", json.dumps(rows))
            self.assertTrue(next(r for r in rows if r["type"] == "tool_result")["truncated"])

    def test_native_event_conflicts_are_rejected(self):
        for agent in AGENTS:
            entry = copy.deepcopy(fixtures(agent)[0])
            entry["payload"]["hook_event_name"] = "unsupported-event"
            self.assertIsNone(normalize(entry["payload"], load(agent), entry["event"]))

    def test_intervening_events_keep_positions_and_existing_prefix_bytes(self):
        entries = fixtures("auggie")
        for entry in entries[:4]:
            self.dispatch("auggie", entry)
        path = self.out / "auggie" / (SESSION + ".jsonl")
        prefix = path.read_bytes()
        for entry in entries[4:]:
            self.dispatch("auggie", entry)
        self.assertTrue(path.read_bytes().startswith(prefix))
        rows = self.rows("auggie")
        notice = next(i for i, r in enumerate(rows) if r.get("origin") == "notice")
        result = next(i for i, r in enumerate(rows) if r["type"] == "tool_result")
        self.assertLess(notice, result)

    def test_firebender_child_lifecycle_is_separate_without_guessed_parent(self):
        self.play("firebender")
        rows = self.rows("firebender", "synthetic-child")
        self.assertEqual(rows[0]["sessionId"], "synthetic-child")
        self.assertNotIn("parent", rows[0])
        self.assertFalse(any("endedAt" in r for r in rows))

    def test_resume_keeps_identity_and_cannot_establish_start_time(self):
        for agent in ("junie", "tabnine"):
            entry = copy.deepcopy(fixtures(agent)[0])
            entry["payload"]["source"] = "resume"
            self.dispatch(agent, entry)
            before = self.rows(agent)
            self.assertNotIn("startedAt", before[0])
            self.assertNotIn("cwd", before[0])
            self.assertTrue(any(r["type"] == "gap" for r in before))
            self.dispatch(agent, entry)
            self.assertEqual(sum(r["type"] == "session" for r in self.rows(agent)), 1)

    def test_native_install_shapes_and_round_trips_preserve_other_configuration(self):
        for agent in AGENTS:
            script = Path("/synthetic/install with spaces") / agent / "record.py"
            hooks = registrations(agent, load(agent), script, Path("/synthetic/out"))
            first = next(iter(hooks))
            other = {"command": "unrelated", "timeout": 9}
            if agent == "kiro":
                original = {"version": "v1", "privateSetting": True, "hooks": [
                    {"name": "Other", "trigger": "Stop", "action": other}]}
            elif agent == "antigravity":
                original = {"other": {"enabled": False, "PreToolUse": [{"matcher": "view_file", "hooks": [other]}]},
                            "empty-group": {}, "empty-event": {"Stop": []},
                            "asr-session-recorder": {"Stop": [other]}}
            else:
                entries = [other] if agent == "firebender" else [{"matcher": "Read", "hooks": [other]}]
                original = {"privateSetting": True, "hooks": {first: entries}}
                if agent == "firebender":
                    original["version"] = 1
            path = Path("settings.json")
            added = merge_native(agent, original, hooks, script, path)
            self.assertEqual(merge_native(agent, added, hooks, script, path), added)
            self.assertEqual(merge_native(agent, added, hooks, script, path, True), original)
            if agent == "junie":
                self.assertTrue(all(h["async"] for group in hooks.values() for e in group for h in e["hooks"]))
            if agent in {"auggie", "tabnine"}:
                self.assertTrue(all(h["timeout"] == 1000 for group in hooks.values() for e in group for h in e["hooks"]))
            if agent == "firebender":
                self.assertTrue({"beforeMCPExecution", "beforeReadFile"}.isdisjoint(hooks))
            if agent == "antigravity":
                self.assertIn("hooks", hooks["PreToolUse"][0])
                self.assertNotIn("hooks", hooks["SessionStart"][0])
                self.assertFalse(added["other"]["enabled"])

    def test_devin_unwrapped_hooks_file_preserves_other_commands(self):
        script = Path("/synthetic/install/devin/record.py")
        original = {"PreToolUse": [{"hooks": [{"command": "unrelated"}]}]}
        hooks = registrations("devin", load("devin"), script, Path("/synthetic/out"))
        path = Path("hooks.v1.json")
        added = merge_native("devin", original, hooks, script, path)
        self.assertNotIn("hooks", added)
        self.assertEqual(merge_native("devin", added, hooks, script, path, True), original)

    def test_installed_commands_run_from_outside_the_repository(self):
        for agent in AGENTS:
            prefix = self.root / "installed with spaces 'quote'"
            config = self.root / (agent + ".json")
            args = [sys.executable, "-I", "-S", str(CORE / "install.py"), agent, "--prefix", str(prefix),
                    "--config", str(config), "--output-dir", str(self.out)]
            installed = subprocess.run(args, capture_output=True)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            document = json.loads(config.read_text())
            native = fixtures(agent)[0]["event"]
            if agent == "kiro":
                command = document["hooks"][0]["action"]["command"]
            elif agent == "antigravity":
                command = document["asr-session-recorder"][native][0]["command"]
            elif agent == "firebender":
                command = document["hooks"][native][0]["command"]
            else:
                command = document["hooks"][native][0]["hooks"][0]["command"]
            result = subprocess.run(command, shell=True, cwd=self.root, input=encode(fixtures(agent)[0]["payload"]), capture_output=True)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, response(agent, native), b""))
            self.assertTrue(self.rows(agent))
            self.assertTrue((prefix / agent / "README.md").exists())
            removed = subprocess.run(args + ["--uninstall"], capture_output=True)
            self.assertEqual(removed.returncode, 0, removed.stderr)
            document = json.loads(config.read_text())
            self.assertEqual(document, {"version": "v1", "hooks": []} if agent == "kiro" else
                             {"version": 1} if agent == "firebender" else {})

    def test_entry_points_fail_open_for_bad_payloads_and_unavailable_core(self):
        for agent in AGENTS:
            native = "PreToolUse" if agent != "firebender" else "preToolUse"
            for raw in (b"{", b"[]", b'{"session_id":"one","session_id":"two"}', b"x" * (1024 * 1024 + 1)):
                result = subprocess.run([sys.executable, "-I", "-S", str(CORE.parent / agent / "record.py"), native],
                                        input=raw, capture_output=True, timeout=3)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, response(agent, native), b""))
            detached = self.root / agent / "record.py"
            detached.parent.mkdir()
            detached.write_bytes((CORE.parent / agent / "record.py").read_bytes())
            result = subprocess.run([sys.executable, "-I", "-S", str(detached), native], input=b"{}", capture_output=True)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, response(agent, native), b""))

    def test_antigravity_neutral_response_survives_a_real_recorder_deadline(self):
        process = subprocess.Popen([sys.executable, "-I", "-S", str(CORE.parent / "antigravity/record.py"), "PreToolUse"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            # Keep stdin open with no data so the recorder's own alarm expires.
            self.assertEqual(process.wait(timeout=2), 0)
            self.assertEqual(process.stdout.read(), response("antigravity", "PreToolUse"))
            self.assertEqual(process.stderr.read(), b"")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stdin.close()
            process.stdout.close()
            process.stderr.close()


def tearDownModule():
    print("Additional adapter ASR validation: " + json.dumps(TOTAL, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
