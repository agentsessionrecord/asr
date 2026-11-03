from concurrent.futures import ThreadPoolExecutor
import fcntl
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import types

import pytest

from asr_plugin_core import Observer, Store, VENDOR, event, now, passive

ROOT = Path(__file__).resolve().parents[3]
AGENTS = ["hermes", "astrbot", "deepagents", "openhands", "mistral-vibe"]


def recorder(agent, path, full=True):
    return importlib.import_module("asr_" + agent.replace("-", "_")).Recorder(path, full=full)


def replay(agent, path, full=True):
    observer = recorder(agent, path, full)
    payloads = json.loads((ROOT / "plugins" / agent / "fixtures/hooks.json").read_text())
    for i, payload in enumerate(payloads):
        observer(payload, f"2026-11-01T12:00:{i:02d}Z")
    file, = path.glob("*.jsonl")
    return file, [json.loads(line) for line in file.read_text().splitlines()]


def validate(path):
    completed = subprocess.run(["node", str(ROOT / "tools/validator/bin/asr-validate.js"), "--json", str(path)], capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return json.loads(completed.stdout)


@pytest.mark.parametrize("agent", AGENTS)
@pytest.mark.parametrize("full", [True, False])
def test_fixture_roundtrip_and_validator(agent, full, tmp_path):
    file, rows = replay(agent, tmp_path, full)
    assert rows[0]["producer"]["method"] == "recorder"
    assert rows[0]["sessionId"] == "synthetic-session"
    assert "approvals" in rows[0]["missing"]
    validate(file)
    if full:
        assert file.read_bytes() == (ROOT / "plugins" / agent / "fixtures/session.jsonl").read_bytes()
    else:
        assert all("input" not in row and "inputText" not in row for row in rows)
        assert "printf" not in file.read_text()
        assert "content" in rows[0]["missing"]


@pytest.mark.parametrize("agent", ["hermes", "deepagents", "mistral-vibe"])
def test_effective_arguments_are_late_and_prefix_is_immutable(agent, tmp_path):
    file, rows = replay(agent, tmp_path)
    calls = [r for r in rows if r["type"] == "tool_call"]
    results = [r for r in rows if r["type"] == "tool_result"]
    assert calls[0]["_meta"][VENDOR]["requestedInput"]["command"] == "printf original"
    assert "input" not in calls[0]
    assert results[0]["input"] == {"command": "printf ready"}
    assert results[0]["callId"] == calls[0]["callId"]
    prefix = file.read_bytes()
    p = {"session_id": "synthetic-session", "hook": "on_session_end", "hook_event_name": "Stop"}
    recorder(agent, tmp_path)(p, "2026-11-01T12:01:00Z")
    assert file.read_bytes().startswith(prefix)
    validate(file)


def test_hermes_explicit_approvals_and_run_end(tmp_path):
    _, rows = replay("hermes", tmp_path)
    approval, = [r for r in rows if r["type"] == "approval"]
    assert (approval["decision"], approval["by"], approval["scope"]) == ("approved", "user", "once")
    assert sum("endedAt" in r for r in rows) == 1
    assert rows[-1]["endedAt"] == "2026-11-01T12:00:06Z"
    assert rows[0]["startedAt"] == "2026-11-01T12:00:00Z"


@pytest.mark.parametrize("choice,expected,by,scope", [
    ("once", "approved", "user", "once"), ("session", "approved", "user", "session"),
    ("always", "approved", "user", "always"), ("deny", "denied", "user", None),
    ("timeout", "cancelled", None, None), ("cancelled", "cancelled", None, None),
    ("smart_approve", "approved", "classifier", None), ("smart_deny", "denied", "classifier", None),
    ("unknown", None, None, None),
])
def test_hermes_decision_vocabulary(choice, expected, by, scope, tmp_path):
    rec = recorder("hermes", tmp_path)
    rec({"hook": "post_approval_response", "session_id": "synthetic-session", "choice": choice, "decided_by": "aux_llm"}, now())
    file, = tmp_path.glob("*.jsonl")
    rows = [json.loads(line) for line in file.read_text().splitlines()]
    approvals = [r for r in rows if r["type"] == "approval"]
    if expected is None:
        assert not approvals
    else:
        approval, = approvals
        assert approval["decision"] == expected
        assert approval.get("by") == by
        assert approval.get("scope") == scope
    validate(file)


def test_hermes_block_does_not_invent_a_hook_approval(tmp_path):
    rec = recorder("hermes", tmp_path)
    rec({"session_id": "synthetic-session", "hook": "post_tool_call", "tool_call_id": "synthetic-blocked", "status": "blocked", "result": "blocked"}, now())
    file, = tmp_path.glob("*.jsonl")
    rows = [json.loads(line) for line in file.read_text().splitlines()]
    assert not any(r["type"] == "approval" for r in rows)
    assert rows[-1]["status"] == "denied"
    validate(file)


@pytest.mark.parametrize("choice,decision,scope", [
    ("session", "approved", "session"), ("always", "approved", "always"),
    ("deny", "denied", None), ("timeout", "cancelled", None),
    ("cancelled", "cancelled", None),
])
def test_hermes_coalesced_decision_reuses_policy(choice, decision, scope, monkeypatch, tmp_path):
    from asr_hermes import register
    monkeypatch.setenv("ASR_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("ASR_CONTENT", "full")
    callbacks = {}
    observer = register(types.SimpleNamespace(register_hook=lambda name, cb: callbacks.setdefault(name, cb)))
    assert callbacks["post_approval_response"](session_id="synthetic-session", choice=choice, coalesced=True) is None
    observer.flush()
    file, = tmp_path.glob("*.jsonl")
    approval = json.loads(file.read_text().splitlines()[-1])
    assert approval["decision"] == decision
    assert approval.get("scope") == scope
    assert approval.get("by") == (None if decision == "cancelled" else "policy")
    assert approval["native"]["coalesced"] is True
    validate(file)


@pytest.mark.parametrize("field,value", [
    ("tool_call_id", "synthetic-" + "a" * 17000),
    ("turn_id", "synthetic-" + "a" * 17000),
    ("tool_call_id", "synthetic-private-identifier"),
])
def test_native_identifiers_are_not_changed_by_privacy_filters(field, value, monkeypatch, tmp_path):
    monkeypatch.setenv("SYNTHETIC_API_KEY", "synthetic-private-identifier")
    rec = recorder("hermes", tmp_path)
    rec({"hook": "pre_tool_call", "session_id": "synthetic-session", "tool_name": "terminal", field: value}, now())
    file, = tmp_path.glob("*.jsonl")
    rows = [json.loads(line) for line in file.read_text().splitlines()]
    assert not any(row["type"] == "tool_call" for row in rows)
    assert rows[-1]["type"] == "gap"
    assert "synthetic-private-identifier" not in file.read_text()
    validate(file)


def test_hermes_child_uses_native_relationship_and_escaped_reference(tmp_path):
    rec = recorder("hermes", tmp_path)
    rec({"hook": "subagent_start", "parent_session_id": "synthetic:parent #1", "child_session_id": "synthetic-child", "child_role": "reviewer"}, now())
    files = list(tmp_path.glob("*.jsonl"))
    assert len(files) == 2
    for file in files:
        rows = [json.loads(line) for line in file.read_text().splitlines()]
        if rows[0]["sessionId"] == "synthetic-child":
            assert rows[0]["parent"]["session"] == "hermes:synthetic%3Aparent%20%231"
            assert "startedAt" in rows[0]
        validate(file)


@pytest.mark.parametrize("agent", ["astrbot", "openhands"])
def test_no_pairing_without_native_call_ids(agent, tmp_path):
    file, rows = replay(agent, tmp_path)
    calls = [r for r in rows if r["type"] == "tool_call"]
    results = [r for r in rows if r["type"] == "tool_result"]
    assert calls and results
    assert len({r["callId"] for r in calls}) == len(calls)
    assert all("callId" not in r and "input" not in r for r in results)
    assert all("input" not in r for r in calls)
    assert "call_correlation" in rows[0]["missing"]
    validate(file)


def test_vibe_duration_and_lifecycle_are_not_fabricated(tmp_path):
    _, rows = replay("mistral-vibe", tmp_path)
    assert not any("endedAt" in r or "startedAt" in r or "durationMs" in r for r in rows)
    assert [r for r in rows if r["type"] == "tool_result"][0]["status"] == "completed"


@pytest.mark.parametrize("agent", ["deepagents", "openhands"])
def test_stop_and_permission_request_are_not_decisions_or_session_end(agent, tmp_path):
    rec = recorder(agent, tmp_path)
    for name in ["PermissionRequest", "Stop"]:
        rec({"session_id": "synthetic-session", "hook_event_name": name, "event_type": name}, now())
    file, = tmp_path.glob("*.jsonl")
    rows = [json.loads(line) for line in file.read_text().splitlines()]
    assert not any("endedAt" in r or r["type"] == "approval" for r in rows)
    validate(file)


def test_deepagents_failures_and_null_late_input(tmp_path):
    rec = recorder("deepagents", tmp_path)
    rec({"session_id": "synthetic-session", "hook_event_name": "PreToolUse", "tool_use_id": "synthetic-call", "tool_name": "Bash", "tool_input": {}}, now())
    rec({"session_id": "synthetic-session", "hook_event_name": "PostToolUseFailure", "tool_use_id": "synthetic-call", "tool_input": None, "is_interrupt": True, "error": "synthetic interruption", "duration_ms": 0}, now())
    file, = tmp_path.glob("*.jsonl")
    last = json.loads(file.read_text().splitlines()[-1])
    assert last["status"] == "interrupted"
    assert "input" in last and last["input"] is None
    assert last["durationMs"] == 0
    validate(file)


def test_privacy_excludes_known_env_secrets_and_sensitive_keys(monkeypatch, tmp_path):
    secret = "synthetic-" + "confidential" * 3
    monkeypatch.setenv("SYNTHETIC_API_KEY", secret)
    rec = recorder("hermes", tmp_path)
    rec({"session_id": "synthetic-session", "hook": "pre_tool_call", "tool_call_id": "synthetic-call", "tool_name": "terminal", "args": {"command": "printf " + secret, "password": "synthetic-secret"}}, now())
    file, = tmp_path.glob("*.jsonl")
    assert secret not in file.read_text()
    assert "synthetic-secret" not in file.read_text()
    assert '"truncated":true' in file.read_text()
    rows = [json.loads(line) for line in file.read_text().splitlines()]
    losses = {loss for row in rows for loss in row.get("missing", [])}
    assert "redacted_content" in losses and "redacted" not in losses
    validate(file)


def test_large_native_numbers_and_long_text_are_declared(tmp_path):
    rec = recorder("hermes", tmp_path)
    rec({"session_id": 2**60, "hook": "pre_tool_call", "tool_call_id": 2**60 + 1, "tool_name": "terminal", "args": {"integer": 2**60, "text": "a" * 20000}}, now())
    file, = tmp_path.glob("*.jsonl")
    rows = [json.loads(line) for line in file.read_text().splitlines()]
    assert rows[0]["sessionId"] == str(2**60)
    assert rows[-1]["callId"] == str(2**60 + 1)
    assert rows[-1]["_meta"][VENDOR]["requestedInput"]["integer"] == str(2**60)
    assert rows[-1]["truncated"] is True
    validate(file)


def test_redacted_header_uses_content_loss_name(monkeypatch, tmp_path):
    secret = "synthetic-private-parent"
    monkeypatch.setenv("SYNTHETIC_API_KEY", secret)
    store = Store("hermes", "synthetic", tmp_path, full=True)
    with store.transaction("synthetic-session", now(), start=True, parent=secret):
        pass
    file, = tmp_path.glob("*.jsonl")
    header = json.loads(file.read_text().splitlines()[0])
    assert header["truncated"] is True
    assert "redacted_content" in header["missing"] and "redacted" not in header["missing"]
    assert secret not in file.read_text()
    validate(file)


def test_lock_contention_drops_quickly_then_emits_gap(tmp_path):
    store = Store("hermes", "synthetic", tmp_path, full=True)
    stem = "hermes-" + hashlib.sha256(b"synthetic-session").hexdigest()
    with (tmp_path / (stem + ".lock")).open("w") as locked:
        os.chmod(locked.name, 0o600)
        fcntl.flock(locked, fcntl.LOCK_EX)
        with store.transaction("synthetic-session", now()) as sink:
            assert sink is None
    with store.transaction("synthetic-session", now()) as sink:
        sink.append(event("synthetic"))
    file, = tmp_path.glob("*.jsonl")
    assert "A callback could not be recorded." in file.read_text()
    validate(file)


def test_concurrent_sessions_and_private_permissions(tmp_path):
    def write(i):
        store = Store("hermes", "synthetic", tmp_path, full=True)
        with store.transaction("synthetic-" + str(i), now(), start=True) as sink:
            sink.append(event("synthetic"))
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(write, range(4)))
    for file in tmp_path.glob("*.jsonl"):
        assert file.stat().st_mode & 0o777 == 0o600
        validate(file)


def test_observer_snapshots_mutable_payload_and_declares_overflow():
    entered, release = threading.Event(), threading.Event()
    seen = []
    def handle(payload, ts):
        entered.set()
        release.wait(5)
        seen.append(payload)
    observer = Observer(handle, capacity=1)
    payload = {"args": {"value": "original"}}
    observer.submit(payload)
    assert entered.wait(5)
    payload["args"]["value"] = "changed"
    observer.submit({"index": 2})
    observer.submit({"index": 3})
    release.set()
    observer.flush()
    assert seen[0]["args"]["value"] == "original"
    assert seen[1]["_asr_dropped"] is True


def test_hermes_registration_is_observer_only(monkeypatch, tmp_path):
    from asr_hermes import HOOKS, register
    monkeypatch.setenv("ASR_OUTPUT_DIR", str(tmp_path))
    callbacks = {}
    observer = register(types.SimpleNamespace(register_hook=lambda name, cb: callbacks.setdefault(name, cb)))
    assert set(callbacks) == set(HOOKS)
    args = {"command": "printf ready"}
    assert callbacks["pre_tool_call"](session_id="synthetic-session", tool_call_id="synthetic-call", tool_name="terminal", args=args) is None
    assert args == {"command": "printf ready"}
    observer.flush()
    file, = tmp_path.glob("*.jsonl")
    validate(file)


@pytest.mark.parametrize("agent", ["deepagents", "openhands", "mistral-vibe"])
@pytest.mark.parametrize("payload", [b"not JSON", b"[]", b"{}", b'{"session_id":"synthetic"}'])
def test_command_wrappers_always_succeed_silently(agent, payload, tmp_path):
    env = {**os.environ, "ASR_OUTPUT_DIR": str(tmp_path)}
    completed = subprocess.run([sys.executable, str(ROOT / "plugins" / agent / "record.py")], input=payload, capture_output=True, env=env, timeout=5)
    assert (completed.returncode, completed.stdout, completed.stderr) == (0, b"", b"")
    for file in tmp_path.glob("*.jsonl"):
        validate(file)


def test_fail_open_unwritable_output_and_duplicate_result(tmp_path):
    blocked = tmp_path / "blocked"
    blocked.write_text("synthetic file")
    passive(recorder("hermes", blocked), {"session_id": "synthetic-session", "hook": "on_session_start"})
    rec = recorder("hermes", tmp_path / "output")
    payload = {"session_id": "synthetic-session", "hook": "post_tool_call", "tool_call_id": "synthetic-call", "status": "ok"}
    passive(rec, payload)
    passive(rec, payload)
    file, = (tmp_path / "output").glob("*.jsonl")
    rows = [json.loads(line) for line in file.read_text().splitlines()]
    assert sum(r["type"] == "tool_result" for r in rows) == 1
    validate(file)


@pytest.mark.parametrize("full", [False, True])
def test_approval_subject_is_only_sourced(full, tmp_path):
    rec = recorder("hermes", tmp_path, full)
    rec({"hook": "post_approval_response", "session_id": "synthetic-session", "choice": "once"}, now())
    file, = tmp_path.glob("*.jsonl")
    approval = [json.loads(line) for line in file.read_text().splitlines() if json.loads(line)["type"] == "approval"][0]
    assert "subject" not in approval and "callId" not in approval
    rec({"hook": "post_approval_response", "session_id": "synthetic-session", "choice": "once", "command": "printf ready"}, now())
    assert json.loads(file.read_text().splitlines()[-1])["subject"] == "printf ready"
    validate(file)


def test_parent_identity_does_not_file_child_events_into_parent(tmp_path):
    rec = recorder("hermes", tmp_path)
    rec({"hook": "post_tool_call", "parent_session_id": "synthetic-parent", "status": "ok"}, now())
    assert not list(tmp_path.glob("*.jsonl"))


def test_incremental_resume_never_reads_old_records(tmp_path, monkeypatch):
    from agent_session_record import Writer
    rec = recorder("hermes", tmp_path)
    rec({"hook": "on_session_start", "session_id": "synthetic-session"}, now())
    with monkeypatch.context() as patch:
        patch.setattr(Writer, "resume", lambda *a, **kw: pytest.fail("must not revalidate old stream"))
        rec({"hook": "post_tool_call", "session_id": "synthetic-session", "tool_call_id": "call", "status": "ok"}, now())
    file, = tmp_path.glob("*.jsonl")
    assert json.loads(file.read_text().splitlines()[-1])["type"] == "tool_result"
    validate(file)


@pytest.mark.parametrize("damage", ["size", "missing", "malformed", "torn"])
def test_inconsistent_storage_is_visible_and_sealed(tmp_path, damage):
    rec = recorder("hermes", tmp_path)
    rec({"hook": "on_session_start", "session_id": "synthetic-session"}, now())
    file, = tmp_path.glob("*.jsonl")
    state, = tmp_path.glob("*.state.json")
    if damage == "size":
        data = json.loads(state.read_text())
        data["size"] -= 1
        state.write_text(json.dumps(data))
    elif damage == "missing":
        state.unlink()
    elif damage == "malformed":
        state.write_text("invalid")
    else:
        with file.open("ab") as stream:
            stream.write(b'{"torn":')
    prefix = file.read_bytes()
    rec({"hook": "on_session_end", "session_id": "synthetic-session"}, now())
    assert file.read_bytes().startswith(prefix)
    files = list(tmp_path.glob("*.jsonl"))
    assert any("storage inconsistency" in path.read_text() for path in files)
    before = {path: path.read_bytes() for path in files}
    rec({"hook": "on_session_end", "session_id": "synthetic-session"}, now())
    assert all(path.read_bytes() == content for path, content in before.items())
    for path in files:
        validate(path)


def test_command_deadline_and_oversized_input_mark_loss(tmp_path):
    from asr_plugin_core import command_main
    import io
    import time
    from unittest.mock import patch
    handler = recorder("hermes", tmp_path)
    with patch.object(sys, "stdin", types.SimpleNamespace(buffer=io.BytesIO(b"x" * (1024 * 1024 + 1)))):
        command_main(lambda: handler)
    assert (tmp_path / "capture.lost").exists()
    def stalled():
        time.sleep(2)
    with patch.object(sys, "stdin", types.SimpleNamespace(buffer=io.BytesIO(b"{}"))):
        start = time.monotonic()
        command_main(stalled)
        assert time.monotonic() - start < 1.3
    handler({"hook": "on_session_start", "session_id": "synthetic-session"}, now())
    file, = tmp_path.glob("*.jsonl")
    assert "A callback could not be recorded." in file.read_text()
    validate(file)


def test_reasoning_summary_survives_without_opaque_state(tmp_path):
    store = Store("hermes", "synthetic", tmp_path, full=True)
    with store.transaction("synthetic-session", now(), start=True) as sink:
        sink.append({"type": "message", "role": "assistant", "content": [
            {"type": "reasoning", "visibility": "summary", "summary": ["visible summary"], "signature": "opaque-state"}]})
    file, = tmp_path.glob("*.jsonl")
    assert "visible summary" in file.read_text() and "opaque-state" not in file.read_text()
    validate(file)


def test_all_python_cores_share_secret_patterns_and_preserve_token_counts():
    from asr_plugin_core import _clean
    from asr_codex_hooks.recorder import scrub
    from asr_litellm.privacy import Scrubber
    sys.path.insert(0, str(ROOT / "plugins/hooks-core"))
    from content import Content
    forms = json.loads((ROOT / "python/agent_session_record/tests/fixtures/credentials.json").read_text())
    secrets = [f.get("prefix", "".join(f.get("prefixParts", []))) + f["repeat"] * f["count"] + f.get("suffix", "".join(f.get("suffixParts", []))) for f in forms]
    value = {"text": " ".join(secrets), "max_tokens": 1024, "inputTokens": 12, "tokens_used": 8}
    cleaned = [_clean(value, (), [False]), scrub(value, ()), Content(True).clean(value), Scrubber().clean(value)]
    for result in cleaned:
        assert all(secret not in json.dumps(result) for secret in secrets)
        assert result["max_tokens"] == 1024 and result["inputTokens"] == 12 and result["tokens_used"] == 8


def test_sidecars_never_keep_unscrubbed_settings_or_rejected_ids(monkeypatch, tmp_path):
    secret = "synthetic-sidecar-private-value"
    monkeypatch.setenv("SYNTHETIC_API_KEY", secret)
    rec = recorder("deepagents", tmp_path)
    rec({"hook_event_name": "PreToolUse", "session_id": "synthetic-session", "permission_mode": secret,
         "tool_use_id": secret, "tool_name": "Bash"}, now())
    for path in tmp_path.iterdir():
        if path.is_file():
            assert secret not in path.read_text()
    file, = tmp_path.glob("*.jsonl")
    validate(file)


def test_python_hook_conventions_are_shared():
    from agent_session_record.hooks import EXTENSION, HOOK, VENDOR as shared_vendor
    from asr_plugin_core import EXTENSION as plugin_extension
    from asr_codex_hooks.recorder import VENDOR as codex_vendor
    assert plugin_extension == EXTENSION == "org.agentsessionrecord.hooks/v1"
    assert codex_vendor == shared_vendor and HOOK == shared_vendor + "/hook"
    retired = ["ASR_" + "HOOKS_DIR", "ASR_" + "HOOKS_CONTENT", "ASR_" + "LITELLM_OUTPUT",
               "hooks/" + "v1", "hooks/" + "event", "asr-json-" + "hooks", "redacted_or_" + "shortened"]
    sources = [ROOT / "plugins/python-core/src", ROOT / "plugins/codex/src", ROOT / "plugins/hooks-core", ROOT / "recorders/litellm/src"]
    for source in sources:
        for path in source.rglob("*.py"):
            assert all(name not in path.read_text() for name in retired), path


def test_absent_requested_input_is_omitted_and_null_is_preserved(tmp_path):
    rec = recorder("hermes", tmp_path)
    for args in ({}, {"args": None}):
        rec({"hook": "pre_tool_call", "session_id": "synthetic-session", "tool_name": "terminal", **args}, now())
    file, = tmp_path.glob("*.jsonl")
    calls = [json.loads(line) for line in file.read_text().splitlines() if json.loads(line)["type"] == "tool_call"]
    assert "requestedInput" not in calls[0]["_meta"][VENDOR]
    assert calls[1]["_meta"][VENDOR]["requestedInput"] is None
    validate(file)


def test_live_store_records_initial_repository_once(tmp_path):
    repo, output = tmp_path / "repo", tmp_path / "captures"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "initial"], check=True)
    store = Store("com.example.agent", "synthetic-hooks", output, full=True)
    with store.transaction("synthetic", now(), start=True, cwd=str(repo)) as sink:
        sink.append(event("start"))
    path, = output.glob("*.jsonl")
    header = json.loads(path.read_text().splitlines()[0])
    assert header["repos"] == [{"path": str(repo), "branch": "initial"}]
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "later"], check=True)
    with store.transaction("synthetic", now(), start=False, cwd=str(repo)) as sink:
        sink.append(event("resume"))
    assert json.loads(path.read_text().splitlines()[0]) == header
    validate(path)
