import json
from pathlib import Path
import random
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from agent_session_record import Writer, derive_id
from agent_session_record.models import AgentSettings, Inference, SessionInfo, TextPart

ROOT = Path(__file__).resolve().parents[3]


def header(**extra):
    return {"agent": {"name": "com.example.agent"}, "sessionId": "synthetic",
            "producer": {"name": "writer-test", "version": "1.0", "method": "native"}, **extra}


def message(**extra):
    return {"type": "message", "role": "user", "content": [], **extra}


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_example(tmp_path):
    example = ROOT / "python/agent_session_record/examples/session.py"
    assert len(example.read_text().splitlines()) == 30
    subprocess.run([sys.executable, str(example), str(tmp_path / "example.jsonl")], check=True, capture_output=True)


def test_append_preserves_prefix_text_native_ids_and_permissions(tmp_path):
    path = tmp_path / "append.jsonl"
    writer = Writer(path, header())
    first = path.read_bytes()
    content = [{"type": "text", "text": "  café\n\r\n😀\t"}]
    writer.append(message(id="native-id", content=content))
    content[0]["text"] = "changed by caller"
    assert path.read_bytes().startswith(first)
    assert rows(path)[1]["content"][0]["text"] == "  café\n\r\n😀\t"
    assert rows(path)[1]["id"] == "native-id"
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        Writer(path, header())
    writer.close()
    writer.close()
    with pytest.raises(ValueError, match="closed"):
        writer.append(message())


def test_settings_tools_snapshot_approvals_and_declared_losses(tmp_path):
    path = tmp_path / "settings.jsonl"
    with Writer(path, header(missing=["timestamps"])) as writer:
        writer.update({"agentSettings": {"mode": "ask", "approval": False, "sandbox": {"enabled": False},
            "asks": "sometimes", "modelSettings": {"temperature": 0, "reasoningEffort": "high"},
            "externalSandbox": {"kind": "container", "source": "setting", "native": {"id": 9007199254740993}}},
            "tools": [{"name": "echo", "inputSchema": {"type": "object"}}]})
        writer.update({"agentSettings": {"mode": ""}})
        writer.append(SessionInfo(type="session_info", id="clear-reasoning",
            agent_settings=AgentSettings(model_settings={"reasoningEffort": None})))
        writer.update({"agentSettings": {"externalSandbox": {}, "modelSettings": None}})
        writer.append({"type": "tool_call", "id": "call", "callId": "c", "name": "echo", "input": {"value": "requested"}})
        writer.append(message(id="notice", content=[{"type": "text", "text": "Between call and result"}]))
        writer.append({"type": "approval", "callId": "c", "decision": "approved", "by": "policy", "native": {"value": 9007199254740993}})
        writer.append({"type": "tool_result", "callId": "c", "status": "completed", "input": None})
        writer.update({"agentSettings": {"mode": None, "externalSandbox": None}, "tools": [], "missing": ["usage", "model"]})
        writer.update({"missing": []})
        writer.append(Inference(type="inference", id="inference", usage={"inputTokens": 0}))
    records = rows(path)
    assert records[2]["agentSettings"] == {"mode": ""}
    assert records[3]["agentSettings"] == {"modelSettings": {"reasoningEffort": None}}
    assert records[4]["agentSettings"] == {"externalSandbox": {}, "modelSettings": None}
    assert [record["type"] for record in records[5:9]] == ["tool_call", "message", "approval", "tool_result"]
    assert records[7]["native"]["value"] == "9007199254740993"
    assert records[8]["input"] is None
    assert records[9]["tools"] == []
    assert records[10]["missing"] == []
    assert not any("ts" in row or "endedAt" in row for row in records)


def test_rejections_do_not_write_or_consume_positions(tmp_path):
    path = tmp_path / "rejections.jsonl"
    with Writer(path, header()) as writer:
        writer.append({"type": "tool_call", "id": "call", "callId": "c", "name": "echo"})
        writer.append({"type": "tool_result", "id": "result", "callId": "c", "status": "completed"})
        before = path.read_bytes()
        circular = {}
        circular["self"] = circular
        for record in [message(id="call"), {"type": "tool_result", "callId": "c", "status": "completed"},
            {"type": "tool_result", "status": "completed", "input": None, "inputText": ""},
            {"type": "tool_call", "callId": "bad", "input": None, "inputText": ""},
            {"type": "approval", "subject": "host", "decision": "cancelled", "scope": "once"},
            {"type": "approval", "subject": "host", "decision": "approved", "by": "policy", "person": {"name": "Example"}},
            {"type": "session_info"}, {"type": "inference"}, {"type": "session"}, {"type": "annotation"},
            {"type": "message", "role": "user"}, message(id="bad\nID"), message(value=float("nan")),
            message(value=float("inf")), message(value=float(2**53)), message(value=object()),
            message(value={1: "invalid"}), message(value=circular),
            {"type": "inference", "model": {"id": "m"}, "usage": {"inputTokens": 9007199254740993}},
            {"type": "vcs", "action": "commit", "status": "completed", "evidence": "observed", "parents": [], "parentCount": 1},
            {"type": "vcs", "action": "rebase", "status": "completed", "evidence": "observed", "rewrites": [{"from": "a"*40, "to": "a"*40}]},
            {"type": "vcs", "action": "merge", "status": "completed", "evidence": "observed", "commit": "a"*40, "parents": ["b"*64]},
            {"type": "file_change", "path": "a", "op": "move", "status": "applied"},
            message(content=[{"type": "reasoning", "visibility": "encrypted", "text": "forbidden"}])]:
            with pytest.raises((TypeError, ValueError)):
                writer.append(record)
            assert path.read_bytes() == before
        with pytest.raises(ValueError):
            writer.update({"type": "message"})
        writer.append(message())
    expected_path = tmp_path / "expected.jsonl"
    with Writer(expected_path, header()) as expected:
        expected.append({"type": "tool_call", "id": "call", "callId": "c", "name": "echo"})
        expected.append({"type": "tool_result", "id": "result", "callId": "c", "status": "completed"})
        expected.append(message())
    assert path.read_bytes() == expected_path.read_bytes()


def test_all_core_records_and_unknown_data(tmp_path):
    path = tmp_path / "core.jsonl"
    with Writer(path, header(parent={"session": "com.example.agent:parent", "kind": "fork", "copiedThrough": "copy"})) as writer:
        writer.append(message(id="copy", role="_custom", unknown={"number": 9007199254740993}, content=[{"type": "future", "value": False}]))
        writer.append({"type": "inference", "id": "i", "model": {"requested": "alias"}, "cost": {"amount": 0, "currency": "USD"}})
        writer.append({"type": "file_change", "path": "src/main.py", "op": "modify", "status": "applied", "actor": "harness", "edits": [{"oldText": "", "newText": "print(1)\n"}]})
        writer.append({"type": "vcs", "action": "commit", "status": "completed", "evidence": "observed", "actor": "harness", "commit": "a"*40, "parents": [], "parentCount": 0})
        writer.append({"type": "gap", "reason": "not_retained", "count": 0})
    assert rows(path)[1]["unknown"]["number"] == "9007199254740993"
    assert rows(path)[1]["content"] == [{"type": "future", "value": False}]


def test_ordering_and_id_uniqueness_for_generated_sequences(tmp_path):
    for seed in range(1, 25):
        generator = random.Random(seed)
        path = tmp_path / f"property-{seed}.jsonl"
        expected = []
        with Writer(path, header()) as writer:
            for index in range(80):
                text = f"{generator.randrange(2**32)}:\nλ😀"
                expected.append(text)
                writer.append(message(**({"id": f"native-{index}"} if index % 3 == 0 else {}),
                    ts=f"2026-10-31T12:00:{generator.randrange(60):02d}Z", content=[{"type": "text", "text": text}]))
        records = rows(path)
        assert [row["content"][0]["text"] for row in records[1:]] == expected
        assert len({row["id"] for row in records}) == len(records)


def test_id_vectors_and_adversarial_collision(tmp_path):
    vectors = json.loads((ROOT / "packages/types/test/id-vectors.json").read_text())
    for vector in vectors:
        assert derive_id(*vector["args"]) == vector["id"]
    with pytest.raises(ValueError):
        derive_id("scope", "message", -1)
    scope = json.dumps(["com.example.agent", None, "synthetic"], separators=(",", ":"))
    with Writer(tmp_path / "collision.jsonl", header(id=derive_id(scope, "message", 1))) as writer:
        assert writer.append(message()) == derive_id(scope, "message", 1, 1)


def test_partial_system_writes_and_failure_stop_further_appends(tmp_path):
    import os
    original_write = os.write
    path = tmp_path / "partial.jsonl"
    with Writer(path, header()) as writer:
        with patch("agent_session_record.writer.os.write", side_effect=lambda fd, data: original_write(fd, data[:3])):
            writer.append(message(content=[{"type": "text", "text": "😀"*5}]))
        before = path.read_bytes()
        with patch("agent_session_record.writer.os.write", side_effect=OSError("synthetic disk failure")):
            with pytest.raises(OSError):
                writer.append(message())
        with pytest.raises(ValueError, match="failed"):
            writer.append(message())
        assert path.read_bytes() == before


def test_concurrent_calls_write_whole_unique_records(tmp_path):
    path = tmp_path / "concurrent.jsonl"
    with Writer(path, header()) as writer:
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(lambda i: writer.append(message(content=[{"type": "text", "text": str(i)}])), range(120)))
    records = rows(path)
    assert len(set(ids)) == 120
    assert {row["content"][0]["text"] for row in records[1:]} == {str(i) for i in range(120)}


def test_generated_models_preserve_unset_null_falsy_and_extra_values():
    model = AgentSettings(mode=None, approval=False, model_settings={"temperature": 0}, future={"id": "9007199254740993"})
    assert model.model_dump(by_alias=True, exclude_unset=True) == {
        "mode": None, "approval": False, "modelSettings": {"temperature": 0}, "future": {"id": "9007199254740993"}}
    assert AgentSettings().model_dump(exclude_unset=True) == {}
    with pytest.raises(ValidationError):
        TextPart(type="text")
    with pytest.raises(ValidationError):
        Inference(type="inference", id="i", duration_ms=None)


def test_oversized_core_count_metadata_and_declared_loss(tmp_path):
    path = tmp_path / "large-count.jsonl"
    with Writer(path, header(missing=["usage"])) as writer:
        writer.append({"type": "inference", "model": {"id": "example-model"},
            "usage": {"outputTokens": 2**53 - 1, "reasoningTokens": 0},
            "_meta": {"com.example.agent": {"inputTokens": 9007199254740993}}})
        writer.append({"type": "tool_call", "callId": "large-input", "name": "echo",
            "input": {"nativeId": 9007199254740993}})
        writer.append({"type": "tool_result", "callId": "large-input", "status": "completed"})
    records = rows(path)
    assert records[0]["missing"] == ["usage"]
    assert "inputTokens" not in records[1]["usage"]
    assert records[1]["usage"]["outputTokens"] == 2**53 - 1
    assert records[1]["usage"]["reasoningTokens"] == 0
    assert records[1]["_meta"]["com.example.agent"]["inputTokens"] == "9007199254740993"
    assert records[2]["input"]["nativeId"] == "9007199254740993"


def test_call_less_approval_needs_only_decision(tmp_path):
    path = tmp_path / "decision.jsonl"
    with Writer(path, header()) as writer:
        writer.append({"type": "approval", "decision": "approved"})
    assert rows(path)[-1]["decision"] == "approved"
    assert "subject" not in rows(path)[-1]
