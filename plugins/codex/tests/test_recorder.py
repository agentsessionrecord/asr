from concurrent.futures import ThreadPoolExecutor
import fcntl
import json
import os
from pathlib import Path
import subprocess
import signal
import sys
import time

import pytest

from asr_codex_hooks import EVENTS
from asr_codex_hooks.recorder import MAX_INPUT, VENDOR, record

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "hooks.jsonl"
STAMP = "2026-11-01T12:00:00.000000Z"


def event(name, **fields):
    return {"session_id": "synthetic-session", "turn_id": "synthetic-turn",
            "hook_event_name": name, "cwd": "/work/example", "model": "example-model",
            "permission_mode": "default", **fields}


def send(output, name, **fields):
    return record(json.dumps(event(name, **fields)).encode(), output, full=True, receipt=STAMP)


def records(output):
    return [json.loads(line) for file in sorted(output.glob("*.jsonl")) for line in file.read_text().splitlines()]


def validate(output):
    files = list(output.glob("*.jsonl"))
    assert files
    for file in files:
        checked = subprocess.run(["node", str(ROOT / "tools/validator/bin/asr-validate.js"), "--json", str(file)],
                                 capture_output=True, text=True)
        assert checked.returncode == 0, checked.stdout + checked.stderr
        report = json.loads(checked.stdout)
        assert report["errors"] == 0, report


def cli(output, data=b"", action="record", extra=()):
    return subprocess.run([sys.executable, "-m", "asr_codex_hooks", action, "--output", str(output), *extra],
                          input=data, capture_output=True)


def test_synthetic_hooks_rewrite_permissions_and_lifecycle(tmp_path):
    output = tmp_path / "asr"
    for line in FIXTURE.read_bytes().splitlines():
        assert record(line, output, full=True, receipt=STAMP)
    rows = records(output)
    assert rows[0]["startedAt"] == STAMP
    assert rows[-1]["endedAt"] == STAMP
    assert rows[0]["producer"]["method"] == "recorder"
    assert not any(r["type"] == "approval" for r in rows)
    call = next(r for r in rows if r["type"] == "tool_call")
    result = next(r for r in rows if r["type"] == "tool_result")
    assert "input" not in call
    assert call["_meta"][VENDOR]["requestedInput"]["command"] == "printf original"
    assert result["input"] == {"command": "printf rewritten"}
    assert result["content"] == [{"type": "text", "text": "rewritten\n"}]
    assert result["status"] == "unknown"
    assert "exitCode" not in result.get("exec", {})
    request = next(r for r in rows if r.get("_meta", {}).get(VENDOR, {}).get("hook_event_name") == "PermissionRequest")
    assert "callId" not in request
    assert "automatic_reviewer_verdicts" in rows[0]["missing"]
    assert next(output.glob("*.jsonl")).read_bytes() == (FIXTURE.parent / "sample.jsonl").read_bytes()
    validate(output)


def test_all_events_and_config(tmp_path):
    config = cli(tmp_path / "asr", action="config")
    hooks = json.loads(config.stdout)["hooks"]
    assert set(hooks) == set(EVENTS)
    for value in hooks.values():
        handler = value[0]["hooks"][0]
        assert handler["timeout"] == 1
        assert "async" not in handler
    output = tmp_path / "asr"
    for name in EVENTS:
        assert send(output, name, tool_use_id="synthetic-call", tool_name="Bash", tool_input=None,
                    source="startup", last_assistant_message="latest only", prompt="hello")
    assert len([r for r in records(output) if r["type"] == VENDOR + "/hook"]) == len(EVENTS)
    validate(output)


def test_metadata_default_is_silent_and_omits_content(tmp_path):
    output = tmp_path / "asr"
    result = cli(output, json.dumps(event("UserPromptSubmit", prompt="synthetic-private-text")).encode())
    assert (result.returncode, result.stdout, result.stderr) == (0, b"", b"")
    text = next(output.glob("*.jsonl")).read_text()
    assert "synthetic-private-text" not in text and "/work/example" not in text
    assert "content" in records(output)[0]["missing"]
    validate(output)


def test_append_resume_dedup_and_folding_order(tmp_path):
    output = tmp_path / "asr"
    assert send(output, "SessionStart", source="startup")
    assert send(output, "PreToolUse", tool_use_id="call-1", tool_name="Bash", tool_input={"command": "true"})
    file = next(output.glob("*.jsonl"))
    prefix = file.read_bytes()
    assert send(output, "PermissionRequest", tool_name="Bash", tool_input={"command": "true"})
    assert send(output, "PostToolUse", tool_use_id="call-1", tool_name="Bash", tool_input=None, tool_response="")
    assert send(output, "PostToolUse", tool_use_id="call-1", tool_name="Bash", tool_input=None, tool_response="")
    assert send(output, "SessionStart", source="resume")
    assert file.read_bytes().startswith(prefix)
    rows = records(output)
    assert sum(r["type"] == "session" for r in rows) == 1
    assert sum(r["type"] == "tool_result" for r in rows) == 1
    request_index = next(i for i, r in enumerate(rows) if r.get("_meta", {}).get(VENDOR, {}).get("hook_event_name") == "PermissionRequest")
    result_index = next(i for i, r in enumerate(rows) if r["type"] == "tool_result")
    assert request_index < result_index
    assert rows[result_index]["input"] is None
    assert rows[result_index]["content"][0]["text"] == ""
    validate(output)


def test_child_stream_without_guessed_immediate_parent(tmp_path):
    output = tmp_path / "asr"
    assert send(output, "SubagentStart", agent_id="child:one/#", agent_type="reviewer")
    assert send(output, "SubagentStop", agent_id="child:one/#", agent_type="reviewer")
    rows = records(output)
    assert rows[0]["sessionId"] == "child:one/#"
    assert "parent" not in rows[0]
    assert not any("endedAt" in r for r in rows)
    assert all("/" not in p.name for p in output.iterdir())
    validate(output)


@pytest.mark.parametrize("source", ["resume", "compact", "fork"])
def test_noncreation_start_has_no_invented_time_or_initial_cwd(tmp_path, source):
    output = tmp_path / "asr"
    assert send(output, "SessionStart", source=source)
    assert "startedAt" not in records(output)[0]
    assert "cwd" not in records(output)[0]
    validate(output)


def test_known_secrets_and_large_native_numbers(tmp_path, monkeypatch):
    output = tmp_path / "asr"
    credential = "synthetic-runtime-secret-123"
    monkeypatch.setenv("ASR_TEST_API_KEY", credential)
    assert send(output, "PostToolUse", tool_name="mcp__demo__echo", tool_use_id="call-large",
                tool_input={"number": 9007199254740993, "password": "synthetic-secret"},
                tool_response={"isError": False, "content": [{"type": "text", "text": credential}]})
    text = next(output.glob("*.jsonl")).read_text()
    assert credential not in text and "synthetic-secret" not in text
    result = next(r for r in records(output) if r["type"] == "tool_result")
    assert result["input"]["number"] == "9007199254740993"
    assert result["status"] == "completed" and result["truncated"]
    assert any("redacted_content" in r.get("missing", []) for r in records(output))
    assert all("redacted" not in r.get("missing", []) for r in records(output))
    validate(output)


@pytest.mark.parametrize("data", [b"not-json", b"[]", b'{"session_id":"one","session_id":"two"}',
                                  b'{"hook_event_name":"future"}', b"\xff", b"x" * (MAX_INPUT + 1)])
def test_malformed_or_oversize_input_fails_open(tmp_path, data):
    result = cli(tmp_path / "asr", data)
    assert (result.returncode, result.stdout, result.stderr) == (0, b"", b"")


def test_approval_label_is_kept_as_source_json(tmp_path):
    output = tmp_path / "asr"
    assert send(output, "SessionStart", source="startup", permission_mode={"native": True})
    assert any(row.get("agentSettings", {}).get("approval") == {"native": True} for row in records(output))
    validate(output)


def test_blocked_writer_and_partial_tail_are_left_unchanged(tmp_path):
    output = tmp_path / "asr"
    assert send(output, "SessionStart", source="startup")
    file = next(output.glob("*.jsonl"))
    lock = next(output.glob("*.lock"))
    prefix = file.read_bytes()
    with lock.open("rb") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        start = time.monotonic()
        assert not send(output, "Stop")
        assert time.monotonic() - start < 0.4
    assert file.read_bytes() == prefix
    assert send(output, "Stop")
    assert any(r.get("reason") == "not_recorded" for r in records(output))
    assert not list(output.glob("*.lost"))
    with file.open("ab") as handle:
        handle.write(b'{"incomplete":')
    partial = file.read_bytes()
    assert not send(output, "SessionEnd")
    assert file.read_bytes() == partial


def test_switching_content_policy_declares_new_losses(tmp_path):
    output = tmp_path / "asr"
    assert send(output, "SessionStart", source="startup")
    assert record(json.dumps(event("Stop", last_assistant_message="omitted")).encode(), output)
    assert any("content" in r.get("missing", []) for r in records(output)[1:])
    validate(output)


def test_capacity_records_terminal_gap_without_overwriting_prefix(tmp_path, monkeypatch):
    from asr_plugin_core import storage
    output = tmp_path / "asr"
    assert send(output, "SessionStart", source="startup")
    stream = next(output.glob("*.jsonl"))
    prefix = stream.read_bytes()
    monkeypatch.setattr(storage, "MAX_STREAM", len(prefix) + 4096)
    assert not send(output, "UserPromptSubmit", prompt="x" * 5000)
    assert stream.read_bytes().startswith(prefix)
    assert records(output)[-1]["type"] == "gap"
    assert "storage limit" in records(output)[-1]["detail"]
    capped = stream.read_bytes()
    assert not send(output, "SessionEnd")
    assert stream.read_bytes() == capped
    validate(output)


def test_private_files_and_symlink_refusal(tmp_path):
    output = tmp_path / "asr"
    assert send(output, "SessionStart", source="startup")
    assert output.stat().st_mode & 0o777 == 0o700
    for file in output.iterdir():
        assert file.stat().st_mode & 0o777 == 0o600
    stream = next(output.glob("*.jsonl"))
    target = tmp_path / "target"
    target.write_text("do not modify")
    stream.unlink()
    stream.symlink_to(target)
    assert not send(output, "Stop")
    assert target.read_text() == "do not modify"


def test_parallel_callbacks_keep_one_header_and_unique_records(tmp_path):
    output = tmp_path / "asr"
    assert send(output, "SessionStart", source="startup")
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert all(pool.map(lambda i: send(output, "PermissionRequest", tool_name="Bash",
                                         tool_input={"command": str(i)}), range(12)))
    rows = records(output)
    assert len({r["id"] for r in rows}) == len(rows)
    assert sum(r["type"] == "session" for r in rows) == 1
    validate(output)


@pytest.mark.parametrize("storage_failure", [False, True])
def test_wrapped_hook_response_preserves_bytes_and_exit_without_claiming_decision(tmp_path, storage_failure):
    output = tmp_path / "asr"
    if storage_failure:
        output.write_text("not a directory")
    payload = json.dumps(event("PreToolUse", tool_name="Bash", tool_use_id="denied-call")).encode()
    stdout = b'{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny"}}\n'
    script = "import sys; sys.stdout.buffer.write(" + repr(stdout) + "); sys.stderr.buffer.write(b'policy\\n'); sys.exit(2)"
    result = cli(output, payload, "wrap", ("--full", "--", sys.executable, "-c", script))
    assert (result.returncode, result.stdout, result.stderr) == (2, stdout, b"policy\n")
    if storage_failure:
        return
    rows = records(output)
    response = next(r["_meta"][VENDOR] for r in rows if "_meta" in r)
    assert response["commandHookResponse"]["stdout"] == stdout.decode()
    assert response["responseIsProposal"] is True
    assert not any(r["type"] == "approval" for r in rows)
    validate(output)


def test_wrapper_preserves_signal_exit(tmp_path):
    output = tmp_path / "asr"
    script = "import os, signal; os.kill(os.getpid(), signal.SIGTERM)"
    result = cli(output, json.dumps(event("PreToolUse")).encode(), "wrap",
                 ("--", sys.executable, "-c", script))
    assert result.returncode == -signal.SIGTERM
    assert result.stdout == result.stderr == b""
    validate(output)


def test_native_reasoning_representation_drops_opaque_state():
    from asr_codex_hooks.recorder import scrub
    assert scrub({"type": "thinking", "thinking": "", "signature": "opaque"}, ()) == {"type": "reasoning", "visibility": "omitted"}
    assert scrub({"type": "thinking", "thinking": "Visible summary", "signature": "opaque"}, ()) == {"type": "reasoning", "visibility": "summary", "summary": ["Visible summary"]}
    assert scrub({"type": "encrypted_reasoning", "text": "opaque"}, ()) == {"type": "reasoning", "visibility": "encrypted"}
