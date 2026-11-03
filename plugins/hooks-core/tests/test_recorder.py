"""Synthetic protocol and storage checks. Every emitted stream is validated."""

import concurrent.futures
import fcntl
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
from install import merge, registrations
import observer
from projection import META, HOOK, filename
from storage import capture, decode, encode

AGENTS = ("claude-code", "cursor", "copilot-cli", "codebuddy", "qoder", "droid")
SESSION = "synthetic-session"
CALL = "synthetic-call"
SENTINEL = "SYNTHETIC_PRIVATE_VALUE_DO_NOT_SAVE"
TOTAL = {"files": 0, "records": 0, "errors": 0, "warnings": {}}


def event(name, **extra):
    return {"hook_event_name": name, "session_id": SESSION, "cwd": "/work/synthetic", **extra}


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="asr-hook-test-")
        self.root = Path(self.temp.name)
        self.out = self.root / "captures"
        self.out.mkdir(mode=0o700)

    def tearDown(self):
        try:
            for path in self.out.rglob("*.jsonl"):
                if path.is_symlink() or not path.is_file():
                    continue
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

    def emit(self, name, agent="claude-code", **extra):
        payload = event(name, **extra)
        capture(str(self.out / agent), payload["session_id"], payload, payload["session_id"], load(agent))

    def rows(self, agent="claude-code", session=SESSION):
        path = self.out / agent / (filename(session) + ".jsonl")
        return [json.loads(line) for line in path.read_bytes().splitlines()] if path.exists() else []

    def dispatch(self, payload, agent="claude-code", native=None):
        with mock.patch.dict(os.environ, {"ASR_OUTPUT_DIR": str(self.out)}), \
                mock.patch.object(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(encode(payload)))), \
                mock.patch("signal.signal"), mock.patch("signal.setitimer"):
            return observer.main(agent, native)

    def run_hook(self, payload, agent="claude-code", native="SessionStart", raw=False, **env):
        result = subprocess.run([sys.executable, "-I", "-S", str(CORE.parent / agent / "record.py"), native],
            input=payload if raw else encode(payload), capture_output=True,
            env={**os.environ, "ASR_OUTPUT_DIR": str(self.out), **env}, timeout=3)
        code = 1 if agent == "cursor" and native in {"preToolUse", "subagentStart", "beforeSubmitPrompt"} else 0
        self.assertEqual((result.returncode, result.stdout, result.stderr), (code, b"", b""))
        return result

    def test_all_documented_fixtures_in_both_content_modes(self):
        for mode in ("metadata", "full"):
            with mock.patch.dict(os.environ, {"ASR_CONTENT": mode}):
                for agent in AGENTS:
                    fixtures = json.loads((CORE.parent / agent / "fixtures/hooks.json").read_text())
                    for entry in fixtures:
                        payload = dict(entry["payload"])
                        key = "sessionId" if agent == "copilot-cli" else "conversation_id" if agent == "cursor" else "session_id"
                        payload[key] = mode + "-" + agent
                        self.dispatch(payload, agent, entry["event"])
                    rows = self.rows(agent, mode + "-" + agent)
                    self.assertEqual(rows[0]["agent"]["name"], agent)
                    self.assertEqual(rows[0]["producer"]["method"], "recorder")
                    if agent == "cursor":
                        self.assertNotIn("startedAt", rows[0])
                    else:
                        self.assertTrue(rows[0].get("startedAt"))
                    self.assertTrue(any(r.get("endedAt") for r in rows))
                    self.assertFalse(any(r["type"] == "inference" for r in rows))
                    if agent in {"droid", "copilot-cli", "codebuddy"}:
                        results = [r for r in rows if r["type"] == "tool_result"]
                        self.assertTrue(results)
                        self.assertTrue(all("callId" not in r for r in results))

    def test_late_effective_input_folds_at_completion_without_reordering(self):
        with mock.patch.dict(os.environ, {"ASR_CONTENT": "full"}):
            self.emit("SessionStart", source="startup")
        self.emit("PreToolUse", tool_use_id=CALL, tool_name="Bash", tool_input={"command": "printf requested"})
        self.emit("PostToolUse", tool_use_id=CALL, tool_name="Bash", tool_input={"command": "printf effective"},
                  tool_response={"stdout": "effective", "stderr": ""}, duration_ms=0)
        self.emit("Notification", message="intervening notice")
        before = self.rows()
        self.assertFalse(any(r["type"] == "tool_result" for r in before))
        self.emit("PostToolBatch", tool_calls=[{"tool_use_id": CALL, "tool_name": "Bash",
                  "tool_input": {"command": "printf requested"}, "tool_response": "effective\n"}])
        rows = self.rows()
        self.assertEqual(rows[:len(before)], before)
        call = next(r for r in rows if r["type"] == "tool_call")
        result = next(r for r in rows if r["type"] == "tool_result")
        self.assertNotIn("input", call)
        self.assertEqual(call["_meta"][META]["requestedInput"], {"command": "printf requested"})
        self.assertEqual(result["input"], {"command": "printf effective"})
        self.assertEqual(result["content"], [{"type": "text", "text": "effective\n"}])
        self.assertEqual(result["durationMs"], 0)
        self.assertEqual(result["exec"]["stderr"], "")
        self.assertNotIn("exitCode", result["exec"])
        self.assertLess(result["_meta"][META]["firstObservedAt"], result["ts"])
        self.assertFalse(any(r["type"] == "approval" for r in rows))

    def test_request_is_never_a_permission_decision(self):
        self.emit("PreToolUse", tool_use_id=CALL, tool_name="Bash")
        self.emit("PermissionRequest", tool_name="Bash", permission_suggestions=[{"type": "allow"}])
        self.emit("PostToolBatch", tool_calls=[{"tool_use_id": CALL, "tool_name": "Bash", "tool_response": "denied"}])
        self.assertFalse(any(r["type"] == "approval" for r in self.rows()))
        self.assertEqual(next(r for r in self.rows() if r["type"] == "tool_result")["status"], "unknown")
        self.emit("PermissionDenied", tool_use_id=CALL, tool_name="Bash", reason="No verdict")
        approval = next(r for r in self.rows() if r["type"] == "approval")
        self.assertEqual(approval["decision"], "denied")
        self.assertTrue(all(k not in approval for k in ("by", "scope", "person")))

    def test_explicit_denial_and_one_final_result(self):
        self.emit("PreToolUse", tool_use_id=CALL, tool_name="Bash")
        self.emit("PermissionDenied", tool_use_id=CALL, tool_name="Bash")
        self.emit("PostToolBatch", tool_calls=[{"tool_use_id": CALL, "tool_name": "Bash", "tool_response": "refused"}])
        self.emit("Stop")
        self.emit("PostToolBatch", tool_calls=[{"tool_use_id": CALL, "tool_name": "Bash", "tool_response": "duplicate"}])
        results = [r for r in self.rows() if r["type"] == "tool_result"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "denied")

    def test_stop_never_ends_session_but_session_end_does(self):
        self.emit("SessionStart", source="startup")
        self.emit("Stop")
        self.emit("SubagentStop")
        self.assertFalse(any("endedAt" in r for r in self.rows()))
        self.emit("SessionEnd")
        self.assertTrue(self.rows()[-1]["endedAt"])
        count = len(self.rows())
        self.emit("SessionStart", source="resume")
        self.assertEqual(sum(r["type"] == "session" for r in self.rows()), 1)
        self.assertGreater(len(self.rows()), count)

    def test_resumed_first_observation_does_not_claim_initial_cwd_or_start(self):
        self.emit("SessionStart", source="resume")
        self.assertNotIn("startedAt", self.rows()[0])
        self.assertNotIn("cwd", self.rows()[0])
        self.assertTrue(any(r["type"] == "gap" for r in self.rows()))

    def test_child_streams_and_native_reference_encoding(self):
        child = "child:7#one two%"
        self.dispatch(event("SubagentStart", agent_id=child))
        rows = self.rows(session=child)
        self.assertEqual(rows[0]["sessionId"], child)
        self.assertNotIn("parent", rows[0])
        self.emit("PostToolUse", tool_use_id=CALL, tool_name="Agent", tool_response={"agentId": child})
        self.emit("PostToolBatch", tool_calls=[{"tool_use_id": CALL, "tool_name": "Agent", "tool_response": "done"}])
        result = next(r for r in self.rows() if r["type"] == "tool_result")
        self.assertEqual(result["subagent"]["session"], "claude-code:child%3A7%23one%20two%25")

    def test_unknown_and_null_inputs_are_preserved_at_completion(self):
        with mock.patch.dict(os.environ, {"ASR_CONTENT": "full"}):
            self.emit("SessionStart", source="startup")
        self.emit("PreToolUse", tool_use_id=CALL, tool_name="custom")
        self.emit("PostToolUse", tool_use_id=CALL, tool_name="custom", tool_input=None)
        self.emit("Stop")
        result = next(r for r in self.rows() if r["type"] == "tool_result")
        self.assertIn("input", result)
        self.assertIsNone(result["input"])
        self.assertNotIn("inputText", result)

    def test_settings_verbatim_and_change_only(self):
        self.emit("SessionStart", source="startup", permission_mode="default", effort={"level": "high"})
        self.emit("Stop", permission_mode="default", effort={"level": "high"})
        self.emit("Stop", permission_mode="bypassPermissions", effort={"level": "future"})
        settings = [r["agentSettings"] for r in self.rows() if "agentSettings" in r]
        self.assertEqual(settings, [{"approval": "default", "asks": "sometimes", "modelSettings": {"reasoningEffort": "high"}},
                                    {"approval": "bypassPermissions", "modelSettings": {"reasoningEffort": "future"}}])

    def test_display_concatenates_and_marks_missing_chunks(self):
        with mock.patch.dict(os.environ, {"ASR_CONTENT": "full"}):
            self.emit("SessionStart", source="startup")
        self.emit("MessageDisplay", message_id="display", index=0, delta="one\n", final=False)
        self.emit("Notification", message="notice")
        self.emit("MessageDisplay", message_id="display", index=1, delta=" two", final=True)
        message = [r for r in self.rows() if r["type"] == "message"][-1]
        self.assertEqual(message["content"], [{"type": "text", "text": "one\n two"}])
        self.emit("MessageDisplay", message_id="lost", index=2, delta="tail", final=True)
        self.assertEqual(self.rows()[-1]["type"], "gap")

    def test_malformed_parts_cannot_break_stream_and_unknown_parts_survive(self):
        with mock.patch.dict(os.environ, {"ASR_CONTENT": "full"}):
            self.emit("SessionStart", source="startup")
        parts = [{"type": "text"}, {"type": "text", "text": 1},
                 {"type": "resource_link", "uri": "synthetic:"},
                 {"type": "resource", "resource": {"uri": "synthetic:", "blob": "bad"}},
                 {"type": "reasoning", "visibility": "encrypted", "text": "opaque-state"},
                 {"type": "synthetic_unknown", "value": False},
                 {"type": "text", "text": "exact\n", "author": "harness"}]
        self.emit("PostToolBatch", tool_calls=[{"tool_use_id": CALL, "tool_name": "Read", "tool_response": parts}])
        result = next(r for r in self.rows() if r["type"] == "tool_result")
        self.assertEqual(result["content"], [
            {"type": "reasoning", "visibility": "encrypted"},
            {"type": "org.agentsessionrecord.native/content", "_meta": {"org.agentsessionrecord.native": {"native": {"type": "synthetic_unknown", "value": False}}}},
            {"type": "text", "text": "exact\n", "author": "harness"}])
        self.assertTrue(result["truncated"])
        self.assertNotIn("opaque-state", json.dumps(self.rows()))

    def test_post_first_input_is_not_repeated_on_result(self):
        with mock.patch.dict(os.environ, {"ASR_CONTENT": "full"}):
            self.emit("PostToolUse", agent="cursor", tool_use_id=CALL,
                      tool_name="Shell", tool_input={"command": "printf first"})
        rows = self.rows("cursor")
        call = next(r for r in rows if r["type"] == "tool_call")
        result = next(r for r in rows if r["type"] == "tool_result")
        self.assertEqual(call["input"], {"command": "printf first"})
        self.assertNotIn("input", result)

    def test_cursor_failure_and_copilot_model_content(self):
        with mock.patch.dict(os.environ, {"ASR_CONTENT": "full"}):
            self.dispatch({"hook_event_name": "postToolUseFailure", "conversation_id": SESSION,
                           "tool_use_id": CALL, "tool_name": "Shell", "error_message": "refused",
                           "failure_type": "permission_denied"}, "cursor", "postToolUseFailure")
        result = next(r for r in self.rows("cursor") if r["type"] == "tool_result")
        self.assertEqual(result["status"], "denied")
        self.assertFalse(any(r["type"] == "approval" for r in self.rows("cursor")))
        with mock.patch.dict(os.environ, {"ASR_CONTENT": "full"}):
            self.dispatch({"sessionId": SESSION, "toolName": "bash", "toolArgs": {},
                           "toolResult": {"resultType": "success", "textResultForLlm": "exact\n"}},
                          "copilot-cli", "postToolUse")
        result = next(r for r in self.rows("copilot-cli") if r["type"] == "tool_result")
        self.assertEqual(result["content"], [{"type": "text", "text": "exact\n"}])
        self.assertNotIn("callId", result)

    def test_metadata_never_persists_free_text_or_elicitation_answers(self):
        for name in load("claude-code")["events"]:
            self.emit(name, tool_name="Bash", tool_use_id=CALL, tool_input={"command": SENTINEL},
                      tool_response={"stdout": SENTINEL}, prompt=SENTINEL, error=SENTINEL,
                      reason=SENTINEL, message=SENTINEL, last_assistant_message=SENTINEL,
                      compact_summary=SENTINEL, delta=SENTINEL, message_id="display", index=0, final=True)
        for path in self.out.rglob("*"):
            if path.is_file():
                self.assertNotIn(SENTINEL.encode(), path.read_bytes())
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_full_content_redacts_known_secrets_and_interaction_answers(self):
        with mock.patch.dict(os.environ, {"ASR_CONTENT": "full", "EXAMPLE_API_KEY": SENTINEL}):
            self.emit("SessionStart", source="startup")
            self.emit("UserPromptSubmit", prompt="reply " + SENTINEL)
            self.emit("PostToolUse", tool_use_id=CALL, tool_name="AskUserQuestion", tool_response="unmarked-answer")
            self.emit("PostToolBatch", tool_calls=[{"tool_use_id": CALL, "tool_name": "AskUserQuestion", "tool_response": "unmarked-answer"}])
            self.emit("ElicitationResult", content={"answer": "unmarked-answer"})
        for path in self.out.rglob("*"):
            if path.is_file():
                data = path.read_bytes()
                self.assertNotIn(SENTINEL.encode(), data)
                self.assertNotIn(b"unmarked-answer", data)
        self.assertTrue(any(r.get("missing") == ["redacted_content"] for r in self.rows()))
        self.assertTrue(all("redacted" not in r.get("missing", []) for r in self.rows()))

    def test_known_credentials_in_native_ids_do_not_escape(self):
        with mock.patch.dict(os.environ, {"EXAMPLE_API_KEY": SENTINEL}):
            self.emit("SessionStart", source="startup", session_id=SENTINEL)
            self.emit("SessionStart", source="startup")
            self.emit("PreToolUse", tool_use_id=SENTINEL, tool_name="Bash")
        self.assertFalse(self.rows(session=SENTINEL))
        self.assertTrue(any(r["type"] == "gap" and r["reason"] == "redacted" for r in self.rows()))
        for path in self.out.rglob("*"):
            self.assertNotIn(SENTINEL, path.name)
            if path.is_file():
                self.assertNotIn(SENTINEL.encode(), path.read_bytes())

    def test_exact_large_native_numbers(self):
        payload = decode(b'{"hook_event_name":"PreToolUse","session_id":"synthetic-session","tool_use_id":"big","tool_name":"custom","tool_input":{"native":9007199254740993}}')
        self.assertEqual(payload["tool_input"]["native"], "9007199254740993")
        with mock.patch.dict(os.environ, {"ASR_CONTENT": "full"}):
            self.dispatch(payload)
        self.assertIn(b'9007199254740993', (self.out / "claude-code/synthetic-session.jsonl").read_bytes())
        self.assertEqual(decode(b'{"value":9.007199254740993e20}')["value"], "9.007199254740993e20")

    def test_malformed_oversized_conflicting_and_missing_identity_fail_open(self):
        for raw in (b"bad", b"{}", b"null", b'{}\n{}', b'"' + b'x' * 1048576,
                    b'{"session_id":"one","session_id":"two"}', b'{"a":NaN}', b'[' * 2000):
            self.run_hook(raw, raw=True)
        self.run_hook(event("SessionStart", session_id=""))
        self.run_hook(event("Stop"))
        self.assertFalse(self.rows())
        self.assertIsNone(normalize({"hook_event_name": "SessionEnd"}, load("claude-code"), "SessionStart"))

    def test_projection_failure_does_not_leave_an_empty_stream(self):
        with mock.patch("projection.project", side_effect=ValueError("synthetic projection failure")):
            with self.assertRaises(ValueError):
                self.emit("SessionStart", source="startup")
        self.assertFalse(list(self.out.rglob("*.jsonl")))

    def test_cursor_protocol_fails_open_without_permission_output(self):
        for name in ("preToolUse", "subagentStart", "beforeSubmitPrompt"):
            self.run_hook({}, agent="cursor", native=name)
        hooks = registrations("cursor", load("cursor"), Path("/synthetic/record.py"), Path("/synthetic/out"))
        self.assertTrue(all(h[0]["failClosed"] is False for h in hooks.values()))

    def test_deadline_closes_stalled_stdin(self):
        proc = subprocess.Popen([sys.executable, "-I", "-S", str(CORE.parent / "claude-code/record.py"), "SessionStart"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            self.assertEqual(proc.wait(timeout=3), 0)
            self.assertEqual(proc.communicate(), (b"", b""))
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()

    def test_native_session_is_not_a_path(self):
        native = "../session:one#two"
        self.emit("SessionStart", session_id=native, source="startup")
        self.assertEqual(self.rows(session=native)[0]["sessionId"], native)

    def test_append_prefix_stale_index_and_partial_tail(self):
        self.emit("SessionStart", source="startup")
        path = self.out / "claude-code/synthetic-session.jsonl"
        before = path.read_bytes()
        self.emit("UserPromptSubmit", prompt="hello")
        self.assertTrue(path.read_bytes().startswith(before))
        with path.open("ab") as out:
            out.write(b'{"torn":')
        before = path.read_bytes()
        self.run_hook(event("SessionEnd"), native="SessionEnd")
        self.assertEqual(path.read_bytes(), before)

    def test_nonblocking_lock_and_unsafe_output(self):
        self.emit("SessionStart")
        base = self.out / "claude-code"
        before = (base / "synthetic-session.jsonl").read_bytes()
        with (base / "synthetic-session.lock").open("rb") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.run_hook(event("SessionEnd"), native="SessionEnd")
        self.assertEqual((base / "synthetic-session.jsonl").read_bytes(), before)
        self.emit("Stop")
        self.assertTrue(any(r["type"] == "gap" and "concurrent" in r.get("detail", "") for r in self.rows()))
        before = (base / "synthetic-session.jsonl").read_bytes()
        base.chmod(0o755)
        self.run_hook(event("SessionEnd"), native="SessionEnd")
        self.assertEqual((base / "synthetic-session.jsonl").read_bytes(), before)

    def test_symlinks_hardlinks_and_fifo_are_not_written(self):
        base = self.out / "claude-code"
        base.mkdir(mode=0o700, parents=True)
        target = self.root / "private"
        target.write_bytes(b"unchanged")
        path = base / "synthetic-session.jsonl"
        path.symlink_to(target)
        self.run_hook(event("SessionStart"))
        self.assertEqual(target.read_bytes(), b"unchanged")
        path.unlink()
        os.mkfifo(path, 0o600)
        self.run_hook(event("SessionStart"))
        path.unlink()
        os.link(target, base / "synthetic-session.state.tmp")
        self.run_hook(event("SessionStart"))
        self.assertEqual(target.read_bytes(), b"unchanged")

    def test_storage_limit_preserves_initial_header_and_seals_stream(self):
        with mock.patch("storage.MAX_STREAM", 1):
            self.emit("SessionStart", source="startup")
        self.assertEqual([r["type"] for r in self.rows()], ["session", "gap"])
        before = self.rows()
        self.emit("SessionEnd")
        self.assertEqual(self.rows(), before)

    def test_state_cap_is_also_terminal(self):
        self.emit("SessionStart", source="startup")
        with mock.patch("storage.MAX_STATE", 1100):
            self.emit("PreToolUse", tool_use_id=CALL, tool_name="Read")
        self.assertEqual(self.rows()[-1]["type"], "gap")
        before = self.rows()
        self.emit("SessionEnd")
        self.assertEqual(self.rows(), before)

    def test_concurrent_processes_preserve_valid_prefix(self):
        self.emit("SessionStart")
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: self.run_hook(event("UserPromptSubmit"), native="UserPromptSubmit"), range(12)))
        rows = self.rows()
        self.assertEqual(sum(r["type"] == "session" for r in rows), 1)
        self.assertEqual(len({r["id"] for r in rows}), len(rows))

    def test_installer_round_trip_preserves_other_hooks_and_settings(self):
        for agent in AGENTS:
            settings = {"privateSetting": True, "hooks": {next(iter(load(agent)["events"])):
                        [{"command": "unrelated"}] if agent in {"cursor", "copilot-cli"} else [{"matcher": "Read", "hooks": [{"command": "unrelated"}]}]}}
            script = Path("/synthetic/install") / agent / "record.py"
            hooks = registrations(agent, load(agent), script, Path("/synthetic/out"))
            added = merge(settings, hooks, script)
            self.assertEqual(merge(added, hooks, script), added)
            self.assertEqual(merge(added, hooks, script, uninstall=True), settings)
        script = Path("/synthetic/install/droid/record.py")
        original = {"PreToolUse": [{"matcher": "Read", "hooks": [{"command": "unrelated"}]}]}
        hooks = registrations("droid", load("droid"), script, Path("/synthetic/out"))
        added = merge(original, hooks, script, unwrapped=True)
        self.assertNotIn("hooks", added)
        self.assertEqual(merge(added, hooks, script, unwrapped=True, uninstall=True), original)

    def test_installer_creates_self_contained_claude_plugin(self):
        prefix = self.root / "installed with spaces"
        config = self.root / "settings.json"
        args = [sys.executable, "-I", "-S", str(CORE / "install.py"), "claude-code", "--prefix", str(prefix),
                "--config", str(config), "--output-dir", str(self.out)]
        result = subprocess.run(args, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        hooks = json.loads(config.read_text())["hooks"]
        command = hooks["SessionStart"][0]["hooks"][0]["command"]
        result = subprocess.run(command, shell=True, input=encode(event("SessionStart", source="startup")), capture_output=True)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))
        self.assertTrue(self.rows())
        self.assertTrue((prefix / "claude-code/.claude-plugin/plugin.json").is_file())
        result = subprocess.run(args + ["--uninstall"], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("hooks", json.loads(config.read_text()))


    def test_subagent_type_only_updates_child_mode(self):
        self.emit("SessionStart", agent="cursor", agent_type="parent-mode")
        self.emit("SubagentStart", agent="cursor", agent_type="child-mode")
        settings = [r["agentSettings"] for r in self.rows("cursor") if "agentSettings" in r]
        self.assertEqual([r["mode"] for r in settings if "mode" in r], ["parent-mode"])
        config = load("claude-code")
        from projection import project
        state = {"position": 0, "content": "metadata", "calls": {}, "results": {}, "pending": {}, "display": {}}
        rows = project("synthetic-child", "synthetic-parent", event("SubagentStart", agent_type="reviewer"), state, "2026-11-01T12:00:00Z", config)
        self.assertTrue(any(r.get("agentSettings", {}).get("mode") == "reviewer" for r in rows))

    def test_bad_saved_state_seals_with_one_gap(self):
        self.emit("SessionStart", source="startup")
        base = self.out / "claude-code"
        path = base / "synthetic-session.jsonl"
        state = base / "synthetic-session.state.json"
        index = json.loads(state.read_text())
        index["size"] -= 1
        state.write_text(json.dumps(index))
        before = path.read_bytes()
        self.emit("SessionEnd")
        self.assertTrue(path.read_bytes().startswith(before))
        self.assertEqual(self.rows()[-1]["detail"], "Capture stopped after a storage inconsistency.")
        sealed = path.read_bytes()
        self.emit("SessionEnd")
        self.assertEqual(path.read_bytes(), sealed)

    def test_oversized_and_deadline_losses_become_a_gap(self):
        self.emit("SessionStart", source="startup")
        self.run_hook(b"x" * (1024 * 1024 + 1), raw=True)
        self.emit("Stop")
        self.assertTrue(any(r["type"] == "gap" for r in self.rows()))

    def test_thinking_summary_is_visible_and_token_counts_are_not_redacted(self):
        with mock.patch.dict(os.environ, {"ASR_CONTENT": "full"}):
            self.emit("AssistantMessage", message=[{"type": "thinking", "thinking": "visible summary", "signature": "opaque-state"}])
            self.emit("PreToolUse", tool_name="Bash", tool_use_id="count-call", tool_input={"max_tokens": 10, "inputTokens": 4})
        text = (self.out / "claude-code/synthetic-session.jsonl").read_text()
        self.assertIn("visible summary", text)
        self.assertNotIn("opaque-state", text)
        self.assertIn('"max_tokens":10', text)
        self.assertIn('"inputTokens":4', text)


    def test_cursor_first_start_cannot_prove_new_conversation(self):
        self.dispatch({"conversation_id": SESSION, "cwd": "/work/synthetic"}, "cursor", "sessionStart")
        rows = self.rows("cursor")
        self.assertNotIn("startedAt", rows[0])
        self.assertNotIn("cwd", rows[0])
        self.assertIn("history_before_capture", rows[0]["missing"])
        self.assertTrue(any(row["type"] == "gap" for row in rows))


def tearDownModule():
    print("ASR validation: " + json.dumps(TOTAL, sort_keys=True))


if __name__ == "__main__":
    unittest.main()


class StartAndEditTests(unittest.TestCase):
    setUp = RecorderTests.setUp
    tearDown = RecorderTests.tearDown
    emit = RecorderTests.emit
    rows = RecorderTests.rows
    def test_repository_snapshot_is_initial_and_resume_never_reads_git(self):
        repo = self.root / "repo"
        repo.mkdir()
        def git(*args):
            return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()
        git("init", "-q", "-b", "initial")
        git("-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid", "commit", "-q", "--allow-empty", "-m", "Baseline")
        with mock.patch.dict(os.environ, {"ASR_CONTENT": "full"}):
            self.emit("SessionStart", source="startup", cwd=str(repo))
        first = self.rows()[0]
        self.assertEqual(first["repos"][0], {"path": str(repo), "branch": "initial", "head": git("rev-parse", "HEAD")})
        git("checkout", "-q", "-b", "later")
        with mock.patch("shared.repository_snapshot", side_effect=AssertionError("late repository read")):
            self.emit("SessionStart", source="resume", cwd=str(repo))
        self.assertEqual(self.rows()[0], first)

    def test_structured_edit_evidence_at_outcome_not_request_or_batch(self):
        with mock.patch.dict(os.environ, {"ASR_CONTENT": "full"}):
            self.emit("SessionStart", source="startup")
        cases = [
            ("Write", {"file_path": "/work/new.txt", "content": "new\n"}, {"type": "create", "filePath": "/work/new.txt", "content": "new\n"}, "add"),
            ("Write", {}, {"type": "update", "filePath": "/work/old.txt", "originalFile": "old\n", "content": "changed\n"}, "modify"),
            ("Edit", {"file_path": "/work/old.txt", "old_string": "old", "new_string": "new"}, {"filePath": "/work/old.txt", "originalFile": "old\n", "oldString": "old", "newString": "new"}, "modify"),
            ("MultiEdit", {}, {"filePath": "/work/multi.txt", "staged": True, "edits": [{"old_string": "a", "new_string": "b"}]}, "modify"),
        ]
        for index, (tool, inputs, output, op) in enumerate(cases):
            cid = "edit-" + str(index)
            self.emit("PreToolUse", tool_use_id=cid, tool_name=tool, tool_input=inputs)
            self.emit("PostToolUse", tool_use_id=cid, tool_name=tool, tool_input=inputs, tool_response=output)
            self.emit("Notification", message="after edit")
            self.emit("PostToolBatch", tool_calls=[{"tool_use_id": cid, "tool_name": tool, "tool_response": "done"}])
            changes = [row for row in self.rows() if row["type"] == "file_change"]
            self.assertEqual(len(changes), index + 1)
            self.assertEqual(changes[-1]["op"], op)
        self.emit("PostToolUse", tool_use_id="edit-0", tool_name="Write", tool_input=cases[0][1], tool_response=cases[0][2])
        changes = [row for row in self.rows() if row["type"] == "file_change"]
        self.assertEqual(len(changes), 4)
        self.assertEqual(changes[0]["after"], {"text": "new\n"})
        self.assertEqual(changes[1]["before"], {"text": "old\n"})
        self.assertEqual(changes[2]["edits"], [{"oldText": "old", "newText": "new"}])
        self.assertEqual(changes[3]["status"], "proposed")
        self.assertEqual(changes[3]["edits"], [{"oldText": "a", "newText": "b"}])
        self.emit("PostToolUseFailure", tool_use_id="failed", tool_name="Edit", tool_response={"filePath": "/work/old.txt"})
        self.emit("PostToolUse", tool_use_id="text-only", tool_name="Write", tool_response="success")
        self.assertEqual(sum(row["type"] == "file_change" for row in self.rows()), 4)

    def test_git_missing_fails_open_and_metadata_mode_does_not_observe_paths(self):
        with mock.patch.dict(os.environ, {"ASR_CONTENT": "full"}), mock.patch("agent_session_record.repository.subprocess.run", side_effect=FileNotFoundError):
            self.emit("SessionStart", source="startup", cwd=str(self.root))
        self.assertEqual(self.rows()[0]["cwd"], str(self.root))
        self.assertNotIn("repos", self.rows()[0])
        with mock.patch.dict(os.environ, {"ASR_CONTENT": "metadata"}), mock.patch("projection.repository_snapshot", side_effect=AssertionError("metadata Git read")):
            self.emit("SessionStart", source="startup", session_id="metadata", cwd=str(self.root))
        self.assertNotIn("cwd", self.rows(session="metadata")[0])
