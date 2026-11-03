import json
from pathlib import Path

import pytest

from asr_openai_codex_logs import convert

FIXTURE = Path(__file__).parent / "fixtures/codex-logs.jsonl"


def test_unscoped_usage_snapshot_tools_and_explicit_denial(tmp_path):
    stream = convert(FIXTURE.read_bytes())
    output = tmp_path / "codex.jsonl"
    stream.write(output)
    assert output.read_bytes() == FIXTURE.with_name("codex-logs.expected.asr.jsonl").read_bytes()
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert not any(row["type"] == "inference" for row in rows)
    assert not any("usage" in row for row in rows)
    assert "usage" in rows[0]["missing"]
    call = next(row for row in rows if row["type"] == "tool_call")
    assert call["callId"] == "synthetic-tool" and "ts" not in call
    approval = next(row for row in rows if row["type"] == "approval")
    assert approval["decision"] == "denied" and "by" not in approval
    assert not any(row["type"] in ("vcs", "file_change") for row in rows)


def test_corrupt_lines_recover_unknown_events_remain_visible_and_no_false_calls(tmp_path):
    row = json.loads(FIXTURE.read_text().splitlines()[0])
    row["event_details"].pop("call_id")
    row["event_details"].pop("token_usage")
    stream = convert((json.dumps(row) + '\n{"broken":\n' + json.dumps({**row, "event_id": "other", "event_type": "FUTURE_EVENT"}) + '\n{}').encode())
    stream.write(tmp_path / "corrupt.jsonl")
    assert not any(row["type"] == "inference" for row in stream.records)
    assert sum(row["type"] == "gap" for row in stream.records) == 3


def test_mixed_session_input_is_rejected():
    row = json.loads(FIXTURE.read_text().splitlines()[0])
    row["event_details"]["session_id"] = "another-session"
    with pytest.raises(ValueError):
        convert(FIXTURE.read_bytes() + (json.dumps(row) + '\n').encode())
