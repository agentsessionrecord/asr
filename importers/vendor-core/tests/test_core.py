from decimal import Decimal
import json
from pathlib import Path

import pytest

from asr_importer_core import META, Stream, json_lines, loads, native, scrub, usage


def test_shared_credential_rules_preserve_counts_and_public_author():
    value = {'apiKey': 'synthetic-private-value', 'clientSecret': 'synthetic-client-value',
             'accesskey': 'synthetic-legacy-value',
             'GIT_AUTHOR_NAME': 'Synthetic Author', 'inputTokens': 15, 'max_tokens': 32,
             'text': 'sess-' + 's' * 20, 'url': 'https://synthetic:private@example.com/path'}
    safe, changed = scrub(value)
    assert changed
    assert safe['apiKey'] == safe['clientSecret'] == safe['text'] == '[redacted]'
    assert safe['accesskey'] == '[redacted]'
    assert safe['GIT_AUTHOR_NAME'] == 'Synthetic Author'
    assert safe['inputTokens'] == 15 and safe['max_tokens'] == 32
    assert safe['url'] == 'https://[redacted]example.com/path'


def test_exact_numbers_duplicate_keys_and_incomplete_lines():
    value = loads('{"id":9007199254740993,"decimal":0.1234567890123456789}')
    assert native(value) == {"id": "9007199254740993", "decimal": "0.1234567890123456789"}
    with pytest.raises(ValueError):
        loads('{"x":1,"x":2}')
    with pytest.raises(ValueError):
        loads('{"x":NaN}')
    assert list(json_lines(b'{}\n{"bad":\n{}')) == [(0, {}), (1, None), (2, None)]


def test_inclusive_usage_and_unknown_components():
    assert usage({"input_tokens": 10, "cache_read_input_tokens": 2, "cache_creation_input_tokens": 3, "output_tokens": 0}, anthropic=True) == {"inputTokens": 15, "cacheReadTokens": 2, "cacheWriteTokens": 3, "outputTokens": 0}
    assert usage({"input_tokens": 10, "cached_input_tokens": 2})["inputTokens"] == 10
    assert "inputTokens" not in usage({"input_tokens": 10, "cache_read_input_tokens": 2**60}, anthropic=True)
    assert "inputTokens" not in usage({"input_tokens": 2**53 - 1, "cache_read_input_tokens": 1}, anthropic=True)


def test_secrets_are_removed_from_content_arguments_metadata_and_header(tmp_path):
    token = "sk-" + "synthetic" * 5
    stream = Stream("codex", "synthetic", "test")
    stream.header["_meta"] = {META: {"authorization": token}}
    stream.add("message", role="user", content=[{"type": "text", "text": token}], meta={"nested": {"api_key": token}, "encrypted_content": "opaque-state"})
    output = tmp_path / "secret.jsonl"
    stream.write(output)
    content = output.read_text()
    assert token not in content and "opaque-state" not in content
    records = [json.loads(line) for line in content.splitlines()]
    assert "secrets" in records[0]["missing"] and records[1]["truncated"]
    assert output.stat().st_mode & 0o777 == 0o600


def test_duplicate_result_ids_remain_unpaired_and_existing_output_is_untouched(tmp_path):
    stream = Stream("codex", "synthetic", "test")
    stream.add("tool_call", source_id="native-call", callId="native-call", name="read")
    stream.add("tool_result", callId="native-call", status="completed")
    stream.add("tool_result", callId="native-call", status="failed")
    output = tmp_path / "duplicate.jsonl"
    stream.write(output)
    records = [json.loads(line) for line in output.read_text().splitlines()]
    assert all("callId" not in row for row in records if row["type"] == "tool_result")
    before = output.read_bytes()
    with pytest.raises(FileExistsError):
        stream.write(output)
    assert output.read_bytes() == before


def test_record_order_and_deterministic_ids(tmp_path):
    outputs = []
    for index in range(2):
        stream = Stream("codex", "synthetic", "test")
        stream.add("message", ts="2026-10-01T11:00:00Z", role="user", content=[])
        stream.add("message", ts="2026-10-01T10:00:00Z", role="assistant", content=[])
        output = tmp_path / f"{index}.jsonl"
        stream.write(output)
        outputs.append(output.read_bytes())
    assert outputs[0] == outputs[1]


def test_secret_fields_inside_json_strings_and_invalid_timestamps(tmp_path):
    stream = Stream("codex", "synthetic", "test")
    body = json.dumps({"api_key": "synthetic-secret", "content": "hello"})
    stream.add("message", ts="2026-10-01 10:00:00+00:00", role="user", content=[], meta={"body": body})
    output = tmp_path / "nested.jsonl"
    stream.write(output)
    assert "synthetic-secret" not in output.read_text()
    assert "ts" not in stream.records[0]


def test_reference_samples_and_examples_validate():
    import subprocess

    root = Path(__file__).resolve().parents[3]
    sources = sorted((root / "samples").glob("*/asr/*.jsonl")) + sorted((root / "examples").glob("*.jsonl"))
    assert sources
    for source in sources:
        result = subprocess.run(["node", str(root / "tools/validator/bin/asr-validate.js"), "--summary", str(source)], capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("module,native_file,arguments", [
    ("asr_anthropic_compliance", "anthropic-compliance/tests/fixtures/local-page.json", []),
    ("asr_openai_codex_logs", "openai-codex-logs/tests/fixtures/codex-logs.jsonl", []),
    ("asr_copilot", "copilot/tests/fixtures/usage.jsonl", ["--session-id", "synthetic-native-session"]),
])
def test_installed_cli_and_output_protection(module, native_file, arguments, tmp_path):
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[3]
    output = tmp_path / "cli.jsonl"
    command = [sys.executable, "-m", module, str(root / "importers" / native_file), *arguments, "--output", str(output)]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    result = subprocess.run(["node", str(root / "tools/validator/bin/asr-validate.js"), str(output)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    before = output.read_bytes()
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 2 and output.read_bytes() == before
