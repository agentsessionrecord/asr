import json
from pathlib import Path

from asr_copilot import convert
from asr_importer_core import META

FIXTURE = Path(__file__).parent / "fixtures/usage.jsonl"


def test_explicit_session_join_requested_served_models_and_inclusive_usage(tmp_path):
    stream = convert(FIXTURE.read_bytes(), session_id="synthetic-native-session")
    output = tmp_path / "copilot.jsonl"
    stream.write(output)
    assert output.read_bytes() == FIXTURE.with_name("usage.expected.asr.jsonl").read_bytes()
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    inference = next(row for row in rows if row["type"] == "inference")
    assert inference["model"] == {"id": "synthetic-served", "requested": "synthetic-requested"}
    assert inference["usage"] == {"inputTokens": 20, "outputTokens": 3, "cacheReadTokens": 5, "reasoningTokens": 0}
    request_message = next(row for row in rows if row["type"] == "message")
    assert "author" not in request_message
    assert request_message["_meta"][META]["request"]["user_id"] == "9007199254740993"
    assert not any(row["type"] in ("approval", "tool_result", "file_change", "vcs") for row in rows)


def test_truncation_and_bad_bodies_do_not_create_calls(tmp_path):
    row = json.loads(FIXTURE.read_text().splitlines()[-1])
    row.update(truncated=True, body='{"partial":')
    stream = convert((json.dumps(row) + '\n').encode(), session_id="synthetic")
    stream.write(tmp_path / "truncated.jsonl")
    assert len(stream.records) == 1 and stream.records[0]["type"] == "gap"
    row.pop("truncated")
    stream = convert((json.dumps(row) + '\n').encode(), session_id="synthetic")
    stream.write(tmp_path / "bad-body.jsonl")
    assert stream.records[0]["reason"] == "unparseable"


def test_repeated_provider_response_is_counted_once_and_history_is_not_execution(tmp_path):
    rows = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
    body = json.loads(rows[0]["body"])
    body["messages"].append({"role": "tool", "tool_call_id": "historical", "content": "old output"})
    rows[0]["body"] = json.dumps(body)
    repeated = {**rows[1], "event_id": "another-observation"}
    stream = convert(''.join(json.dumps(row) + '\n' for row in [*rows, repeated]).encode(), session_id="synthetic")
    stream.write(tmp_path / "deduplicated.jsonl")
    assert sum(row["type"] == "inference" for row in stream.records) == 1
    assert not any(row["type"] == "tool_result" for row in stream.records)


def test_unknown_endpoint_and_unhashable_join_are_not_guessed(tmp_path):
    rows = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
    rows[0]["endpoint"] = "http://[invalid"
    rows[1]["github_request_id"] = {"bad": "join"}
    stream = convert(''.join(json.dumps(row) + '\n' for row in rows).encode(), session_id="synthetic")
    stream.write(tmp_path / "unknown.jsonl")
    inference = next(row for row in stream.records if row["type"] == "inference")
    assert "requested" not in inference["model"]
    assert stream.records[0]["type"] == "gap"
