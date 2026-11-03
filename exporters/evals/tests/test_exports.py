from copy import deepcopy
import socket
import subprocess
import sys

import pytest

from asr_braintrust import export as braintrust
from asr_evals.cli import run
from asr_evals.dataset import rows
from asr_evals.jsonio import dumps, loads
from asr_evals.reader import Session, read_session
from asr_langfuse import export as langfuse
from asr_phoenix import export as phoenix
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from conftest import FIXTURES, ROOT

EXPORTERS = (langfuse, braintrust, phoenix)
STREAMS = [p for directory in (ROOT / "samples", ROOT / "examples") for p in sorted(directory.rglob("*.jsonl"))
           if loads(p.read_text().splitlines()[0]).get("formatVersion") == "0.1"]


@pytest.mark.parametrize("path", STREAMS, ids=lambda p: str(p.relative_to(ROOT)))
def test_every_sample_and_example_exports_to_all_targets(path, options):
    session = read_session(path)
    dataset = rows([session])
    for exporter in EXPORTERS:
        artifacts = exporter([session], dataset, options)
        assert artifacts
        for name, data in artifacts.items():
            if name.endswith(".json"):
                assert loads(data) is not None
            elif name.endswith(".jsonl"):
                assert all(isinstance(loads(line), dict) for line in data.splitlines())
            elif name.endswith(".pb"):
                assert ExportTraceServiceRequest.FromString(data) is not None


def test_langfuse_counts_only_inclusive_tokens_and_usd(session, options):
    artifacts = langfuse([session], rows([session]), options)
    events = loads(artifacts["ingestion.json"])["batch"]
    calls = [e["body"] for e in events if e["type"] == "generation-create"]
    assert len(calls) == 2
    assert calls[0]["usageDetails"] == {"input": 100, "output": 20, "total": 120}
    assert calls[1]["usageDetails"] == {"input": 0, "output": 0, "total": 0}
    assert "model" not in calls[1]
    assert "costDetails" not in calls[1]
    assert "0.123456789012345678901" in artifacts["ingestion.json"]


def test_braintrust_keeps_untimed_usage_without_model_request_guess(session, options):
    options.inference_ts = "unknown"
    events = loads(braintrust([session], rows([session]), options)["project-logs.json"])["events"]
    calls = [e for e in events if e["span_attributes"]["type"] == "llm"]
    assert len(calls) == 2
    assert calls[0]["metrics"]["tokens"] == 120
    assert "start" not in calls[0]["metrics"]
    assert "input" not in calls[0]
    assert all(set(e.get("metrics", {})) <= {"start", "end"} for e in events if e["span_attributes"]["type"] == "task")


def test_phoenix_protobuf_preserves_counts_and_errors_not_success(session, options):
    artifacts = phoenix([session], rows([session]), options)
    request = ExportTraceServiceRequest.FromString(artifacts["traces.otlp.pb"])
    spans = request.resource_spans[0].scope_spans[0].spans
    assert len(spans) == 5
    llm = next(s for s in spans if s.name == "asr.inference")
    attributes = {a.key: a.value for a in llm.attributes}
    assert attributes["llm.token_count.prompt"].int_value == 100
    assert attributes["llm.token_count.completion"].int_value == 20
    assert llm.status.code == 0
    assert len(llm.trace_id) == 16 and len(llm.span_id) == 8
    assert len({s.span_id for s in spans}) == len(spans)
    assert all(s.end_time_unix_nano >= s.start_time_unix_nano for s in spans)


def test_content_is_off_everywhere_and_null_effective_input_survives(session, options):
    for exporter in EXPORTERS:
        artifacts = exporter([session], rows([session]), options)
        text = "".join(v for v in artifacts.values() if isinstance(v, str))
        for sentinel in ("INJECTED_SENTINEL", "OUTPUT_SENTINEL", "RESULT_SENTINEL", "ORIGINAL_INPUT_SENTINEL", "TEST_OUTPUT_SENTINEL", "GAP_DETAIL_SENTINEL", "PRIVATE_TOOL_SENTINEL"):
            assert sentinel not in text
    options.include_content = True
    events = loads(braintrust([session], rows([session], include_content=True), options)["project-logs.json"])["events"]
    tool = next(e for e in events if e["span_attributes"]["name"] == "edit")
    assert "input" in tool and tool["input"] is None
    inference = next(e for e in events if e["span_attributes"]["type"] == "llm")
    assert "input" not in inference
    assert inference["output"][0]["content"][0]["text"] == "OUTPUT_SENTINEL"


def test_no_timing_is_fabricated(session, options):
    header = deepcopy(session.header)
    header.pop("startedAt")
    header.pop("endedAt")
    other = Session(header, session.records, "synthetic")
    options.inference_ts, options.tool_times = "unknown", False
    artifacts = phoenix([other], rows([other]), options)
    assert loads(artifacts["traces.otlp.json"])["resourceSpans"][0]["scopeSpans"][0]["spans"] == []
    assert len(loads(artifacts["omitted.json"])) == 5
    events = loads(langfuse([other], rows([other]), options)["ingestion.json"])["batch"]
    assert "timestamp" not in events[0]["body"]
    assert all(e["type"] not in ("span-create", "generation-create") for e in events)


def test_network_and_commands_from_input_are_never_used(session, options, monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("unexpected_side_effect")
    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(subprocess, "Popen", denied)
    records = deepcopy(session.records)
    records.append({"type": "message", "id": "attack", "role": "user", "content": [{"type": "resource_link", "uri": "http://127.0.0.1:9/untrusted", "name": "untrusted"}]})
    other = Session(session.header, records, "synthetic")
    options.include_content = True
    for exporter in EXPORTERS:
        exporter([other], rows([other], include_content=True), options)


@pytest.mark.parametrize("exporter", (None,) + EXPORTERS)
def test_cli_new_private_artifacts_and_no_overwrite(exporter, tmp_path, monkeypatch):
    destination = tmp_path / "output"
    monkeypatch.setattr(sys, "argv", ["asr-test", str(FIXTURES / "session.jsonl"), "--output", str(destination)])
    assert run("asr-test", exporter) == 0
    assert (destination.stat().st_mode & 0o777) == 0o700
    assert all((p.stat().st_mode & 0o777) == 0o600 for p in destination.iterdir())
    before = {p.name: p.read_bytes() for p in destination.iterdir()}
    assert run("asr-test", exporter) == 1
    assert before == {p.name: p.read_bytes() for p in destination.iterdir()}


def test_synthetic_asr_fixtures_validate():
    result = subprocess.run(["node", "tools/validator/bin/asr-validate.js", "--summary", str(FIXTURES.relative_to(ROOT))], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr + result.stdout
    assert '"errors":0' in result.stdout.replace(" ", "") or "0 error" in result.stdout
