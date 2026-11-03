from copy import deepcopy
import json
from pathlib import Path

import pytest

from asr_anthropic_compliance import convert
from asr_importer_core import META, loads

FIXTURE = Path(__file__).parent / "fixtures/local-page.json"


def test_documented_page_keeps_provenance_and_tool_pairing(tmp_path):
    stream = convert([loads(FIXTURE.read_text())])
    output = tmp_path / "anthropic.jsonl"
    stream.write(output)
    assert output.read_bytes() == FIXTURE.with_name("local-page.expected.asr.jsonl").read_bytes()
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert not any(row["type"] == "inference" for row in rows)
    call = next(row for row in rows if row["type"] == "tool_call")
    assert call["input"] == {"file_path": "/work/example.txt"}
    assert next(row for row in rows if row["type"] == "tool_result")["callId"] == call["callId"]
    unverified = next(row for row in rows if row.get("id") == "synthetic-message-4")
    assert "author" not in unverified and unverified["_meta"][META]["provenance"]["type"] == "client_asserted"
    assert not any(row.get("author") == "human" for row in rows)
    assert "startedAt" not in rows[0] and "endedAt" not in rows[0]
    assert sum(row["type"] == "gap" for row in rows) == 2


def test_truncated_tool_input_is_never_parsed_and_pagination_loss_is_visible(tmp_path):
    page = loads(FIXTURE.read_text())
    part = page["data"][2]["content"][1]
    part.update(input='{"partial":', truncated=True)
    page["next_page"] = "synthetic-next"
    stream = convert([page])
    stream.write(tmp_path / "partial.jsonl")
    call = next(row for row in stream.records if row["type"] == "tool_call")
    assert call["inputText"] == '{"partial":' and call["truncated"]
    assert stream.records[-1]["type"] == "gap"


def test_page_overlap_and_conflict(tmp_path):
    page = loads(FIXTURE.read_text())
    second = deepcopy(page)
    second["data"] = second["data"][-1:]
    stream = convert([page, second])
    assert sum(row["type"] == "tool_call" for row in stream.records) == 1
    second["data"][0]["content"] = [{"type": "text", "text": "conflicting"}]
    stream = convert([page, second])
    stream.write(tmp_path / "overlap.jsonl")
    assert stream.records[-1]["type"] == "gap"
    second["session"]["id"] = "different"
    with pytest.raises(ValueError):
        convert([page, second])


def test_unknown_and_malformed_provenance_remains_conservative(tmp_path):
    page = loads(FIXTURE.read_text())
    page["data"][0]["provenance"] = {"type": "content_unavailable", "reason": {"future": True}}
    page["data"][1]["provenance"] = ["invalid"]
    page["data"][2]["content"].append({"type": "future_block", "value": 0})
    stream = convert([page])
    stream.write(tmp_path / "unknown.jsonl")
    assert any(row["type"] == "gap" and row["reason"] == "unknown" for row in stream.records)
