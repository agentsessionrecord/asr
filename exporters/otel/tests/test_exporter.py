from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from asr_otel import export_sessions, read_session
from asr_otel.exporter import timestamp, update_settings, validate_contracts
from asr_otel.reader import exact_json, parse_json, record_ref, telemetry_id

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).parent / "fixtures"


def attr(item):
    return {a["key"]: a["value"] for a in item["attributes"]}


def scalar(value):
    return next(iter(value.values()))


def spans(export):
    return [s for r in export.traces["resourceSpans"] for scope in r["scopeSpans"] for s in scope["spans"]]


def logs(export):
    return [s for r in export.logs["resourceLogs"] for scope in r["scopeLogs"] for s in scope["logRecords"]]


def by_record(items):
    return {scalar(attr(item)["asr.record_id"]): item for item in items}


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.session = read_session(FIXTURES / "session.jsonl")
        self.child = read_session(FIXTURES / "child.jsonl")
        self.contracts = json.loads((FIXTURES / "contracts.json").read_text())

    def export(self, sessions=None, **kwargs):
        return export_sessions(sessions or [self.session], self.contracts, **kwargs)

    def test_spans_exact_timing_conventions_and_usage(self):
        result = self.export()
        indexed = by_record(spans(result))
        self.assertEqual(set(indexed), {"header", "response:7", "call-1", "spawn"})
        inference = indexed["response:7"]
        values = attr(inference)
        self.assertEqual(int(inference["endTimeUnixNano"]) - int(inference["startTimeUnixNano"]), 500_250_000)
        self.assertEqual(values["gen_ai.usage.input_tokens"], {"intValue": "1200"})
        self.assertEqual(values["gen_ai.usage.output_tokens"], {"intValue": "120"})
        self.assertEqual(values["gen_ai.usage.cache_write.input_tokens"], {"intValue": "100"})
        self.assertEqual(values["gen_ai.request.temperature"], {"doubleValue": 0.0})
        self.assertEqual(values["gen_ai.request.model"], {"stringValue": "example-alias"})
        self.assertEqual(values["gen_ai.response.model"], {"stringValue": "example-served"})
        self.assertEqual(values["openai.request.service_tier"], {"stringValue": "priority"})
        self.assertNotIn("openai.response.service_tier", values)
        self.assertNotIn("gen_ai.response.id", values)
        self.assertEqual(indexed["call-1"]["parentSpanId"], inference["spanId"])
        self.assertNotIn("status", indexed["call-1"])
        self.assertEqual(scalar(attr(indexed["call-1"])["asr.result.status"]), "completed")
        self.assertEqual(scalar(values["asr.timing.basis"]), "receipt")
        self.assertEqual(result.report["logs"], len(self.session.entries))

    def test_ids_use_exact_asr_encoding_and_are_repeatable(self):
        reference = "com.example.agent:test%20space:session%3A7"
        self.assertEqual(self.session.reference, reference)
        self.assertEqual(record_ref(reference, "a:/?# %\x01é"), reference + "#a%3A/?%23%20%25%01é")
        first, second = self.export(), self.export()
        self.assertEqual(first, second)
        inference = by_record(spans(first))["response:7"]
        self.assertEqual(inference["traceId"], hashlib.sha256(reference.encode()).hexdigest()[:32])
        self.assertEqual(inference["spanId"], hashlib.sha256((reference + "#response%3A7").encode()).hexdigest()[:16])
        with patch("asr_otel.reader.hashlib.sha256") as digest:
            digest.return_value.hexdigest.side_effect = ["0" * 64, "1" * 64]
            self.assertEqual(telemetry_id("example", 16), "1" * 16)
            self.assertEqual(digest.call_args_list[-1].args, (b"example#1",))

    def test_no_contract_means_logs_without_guessed_calls(self):
        result = export_sessions([self.session])
        self.assertEqual(len(spans(result)), 1)
        inference = by_record(logs(result))["response:7"]
        self.assertEqual(scalar(attr(inference)["gen_ai.usage.input_tokens"]), "1200")
        self.assertNotIn("gen_ai.response.id", attr(inference))
        self.assertNotIn("openai.request.service_tier", attr(inference))
        self.assertNotIn("gen_ai.request.reasoning.level", attr(inference))
        changed = deepcopy(self.contracts)
        changed["producers"][0]["producer"]["version"] = "other"
        self.assertEqual(len(spans(export_sessions([self.session], changed))), 1)

    def test_readme_first_example_has_logs_and_zero_spans_without_contracts(self):
        session = read_session(ROOT / "examples/coding-session.jsonl")
        result = export_sessions([session])
        self.assertEqual(spans(result), [])
        self.assertEqual(len(logs(result)), len(session.entries))

    def test_configured_settings_never_fill_missing_call_settings(self):
        del self.session.entries[2].data["settings"]
        inference = by_record(spans(self.export()))["response:7"]
        for key in ("gen_ai.request.max_tokens", "gen_ai.request.temperature",
                    "gen_ai.request.reasoning.level", "openai.request.service_tier"):
            self.assertNotIn(key, attr(inference))

    def test_missing_decision_time_has_no_event_or_invented_log_time(self):
        approval = next(e.data for e in self.session.entries if e.data["type"] == "approval")
        del approval["ts"]
        result = self.export()
        self.assertNotIn("timeUnixNano", by_record(logs(result))["approval-1"])
        self.assertNotIn("events", by_record(spans(result))["call-1"])

    def test_recorder_default_timing_basis_and_copied_header(self):
        del self.contracts["producers"][0]["basis"]
        indexed = by_record(spans(self.export()))
        self.assertEqual(scalar(attr(indexed["response:7"])["asr.timing.basis"]), "receipt")
        self.assertEqual(scalar(attr(indexed["header"])["asr.timing.basis"]), "receipt_session_endpoints")
        self.session.entries[0].copied = True
        self.assertNotIn("header", by_record(spans(self.export())))

    def test_cycles_are_unresolved_and_otlp_attributes_have_unique_keys(self):
        call = next(e.data for e in self.session.entries if e.data["id"] == "call-1")
        call["parentCallId"] = "run-1"
        result = self.export([self.session, self.child])
        self.assertNotIn("parentSpanId", by_record(spans(result))["call-1"])
        self.assertIn("cyclic_span_parent", [d["code"] for d in result.report["diagnostics"]])
        for item in [*spans(result), *logs(result)]:
            keys = [a["key"] for a in item["attributes"]]
            self.assertEqual(len(set(keys)), len(keys))

    def test_unbounded_session_keeps_timed_children(self):
        del self.session.header["endedAt"]
        result = self.export()
        self.assertNotIn("header", by_record(spans(result)))
        self.assertNotIn("parentSpanId", by_record(spans(result))["response:7"])
        self.assertIn("parentSpanId", by_record(spans(result))["call-1"])
        self.session.header["endedAt"] = "2026-01-01T00:00:02Z"
        result = self.export()
        self.assertNotIn("header", by_record(spans(result)))
        self.assertIn("session_interval_excludes_activity", [d["code"] for d in result.report["diagnostics"]])

    def test_result_pairing_ambiguous_and_missing_are_unknown(self):
        call = next(e for e in self.session.entries if e.data["id"] == "call-1")
        duplicate = deepcopy(call)
        duplicate.data["id"] = "duplicate-call"
        self.session.entries.append(duplicate)
        result = self.export()
        self.assertNotIn("call-1", by_record(spans(result)))
        self.assertNotIn("duplicate-call", by_record(spans(result)))
        indexed = by_record(logs(result))
        self.assertEqual(scalar(attr(indexed["call-1"])["asr.result.status"]), "unknown")
        self.assertIn("asr.unresolved_references", attr(indexed["result-1"]))
        self.assertIn("asr.unresolved_references", attr(indexed["approval-1"]))
        self.session.entries = [e for e in self.session.entries if e.data["id"] not in {"duplicate-call", "result-1"}]
        self.assertNotIn("call-1", by_record(spans(self.export())))

    def test_copies_no_usage_credit_and_subagent_links_both_sides(self):
        result = self.export([self.session, self.child])
        child_spans = [s for s in spans(result) if scalar(attr(s)["asr.session_ref"]) == self.child.reference]
        self.assertEqual(set(by_record(child_spans)), {"header", "child-response"})
        total_input = sum(int(scalar(attr(item)["gen_ai.usage.input_tokens"]))
                          for item in [*spans(result), *logs(result)] if "gen_ai.usage.input_tokens" in attr(item))
        self.assertEqual(total_input, 1240)
        child_root = by_record(child_spans)["header"]
        self.assertIn("links", child_root)
        self.assertNotIn("parentSpanId", child_root)
        child_call = by_record(child_spans)["child-response"]
        self.assertEqual(scalar(attr(child_call)["gen_ai.usage.output_tokens"]), "0")
        self.assertNotIn("gen_ai.response.model", attr(child_call))
        self.assertNotIn("gen_ai.request.max_tokens", attr(child_call))
        # A link from either file is sufficient.
        del self.child.header["parent"]["callId"]
        self.assertIn("links", [s for s in spans(self.export([self.session, self.child]))
                                if scalar(attr(s)["asr.session_ref"]) == self.child.reference][0])
        self.child.header["parent"]["callId"] = "delegate-1"
        for entry in self.session.entries:
            entry.data.pop("subagent", None)
        self.assertIn("links", [s for s in spans(self.export([self.session, self.child]))
                                if scalar(attr(s)["asr.session_ref"]) == self.child.reference][0])

    def test_missing_union_latest_totals_and_settings(self):
        result = self.export()
        indexed = by_record(logs(result))
        header = attr(indexed["header"])
        self.assertEqual(header["asr.missing"]["arrayValue"]["values"],
                         [{"stringValue": "reasoning"}, {"stringValue": "tool_output"}])
        self.assertEqual(json.loads(scalar(header["asr.source_session_total.usage"])), {"inputTokens": 2100})
        self.assertEqual(json.loads(scalar(header["asr.source_session_total.cost"]))["amount"], .01)
        state = json.loads(scalar(attr(indexed["settings-2"])["asr.agent_settings.effective"]))
        self.assertEqual(state, {"mode": "ask", "externalSandbox": {}, "modelSettings": {"maxOutputTokens": 64}})
        root = by_record(spans(result))["header"]
        self.assertEqual([e["name"] for e in root["events"]],
                         ["asr.session_info", "asr.gap", "asr.session_info", "asr.session_info", "asr.session_info"])
        self.assertEqual(by_record(spans(result))["call-1"]["events"][0]["name"], "asr.approval")

    def test_content_and_identity_are_opt_in_and_effective_input_can_be_empty(self):
        data = exact_json(self.export().logs)
        for marker in ("SYNTHETIC_PRIVATE", "synthetic-user", "person@example.com", "Example Person", "synthetic-approver"):
            self.assertNotIn(marker, data)
        result = self.export(include_content=True)
        self.assertIn("SYNTHETIC_PRIVATE_MESSAGE", exact_json(result.logs))
        self.assertNotIn("synthetic-approver", exact_json(result.logs))
        self.assertEqual(scalar(attr(by_record(spans(result))["call-1"])["asr.tool.effective_inputText"]), "")
        named = self.export(include_identity=True)
        root_attrs = attr(by_record(spans(named))["header"])
        self.assertEqual(scalar(root_attrs["asr.user.name"]), "Example Person")
        self.assertNotIn("user.full_name", root_attrs)
        full = self.export(include_identity=True, user_name_kind="full")
        self.assertIn("user.full_name", attr(by_record(spans(full))["header"]))

    def test_provider_ids_tiers_errors_and_nested_tools(self):
        inference = self.session.entries[2].data
        inference["error"] = {"code": 429, "message": "SYNTHETIC_PRIVATE_ERROR"}
        inference["_meta"] = {"com.example.agent": {"response": "native-response"}}
        mapping = self.contracts["producers"][0]
        mapping["responseIdMetaPath"] = ["com.example.agent", "response"]
        mapping["serviceTier"] = "response"
        result = self.export()
        call = by_record(spans(result))["response:7"]
        self.assertEqual(call["status"], {"code": 2})
        self.assertEqual(scalar(attr(call)["error.type"]), "429")
        self.assertEqual(scalar(attr(call)["gen_ai.response.id"]), "native-response")
        self.assertIn("openai.response.service_tier", attr(call))
        inference["model"]["provider"] = "other"
        self.assertNotIn("openai.response.service_tier", attr(by_record(spans(self.export()))["response:7"]))
        spawn = next(e.data for e in self.session.entries if e.data["id"] == "spawn")
        spawn["parentCallId"] = "run-1"
        result = self.export()
        indexed = by_record(spans(result))
        self.assertEqual(indexed["spawn"]["parentSpanId"], indexed["call-1"]["spanId"])

    def test_stream_order_survives_backwards_timestamps_and_unknown_types(self):
        self.session.entries[1].data["ts"] = "2026-01-01T00:00:09Z"
        self.session.entries[3].data["ts"] = "2026-01-01T00:00:01Z"
        result = self.export()
        self.assertEqual([scalar(attr(x)["asr.record_id"]) for x in logs(result)],
                         [e.data["id"] for e in self.session.entries])
        self.session.entries[3].data["type"] = "com.example.agent/future"
        result = self.export()
        self.assertEqual(result.report["logs"], len(self.session.entries) - 1)
        self.assertIn("unknown_record_type", [d["code"] for d in result.report["diagnostics"]])

    def test_duration_fallback_and_completion_timestamp_contract(self):
        result = next(e.data for e in self.session.entries if e.data["id"] == "result-1")
        del result["ts"]
        result["durationMs"] = Decimal("0.000001")
        indexed = by_record(spans(self.export()))
        self.assertEqual(int(indexed["call-1"]["endTimeUnixNano"]) - int(indexed["call-1"]["startTimeUnixNano"]), 1)
        self.contracts["producers"][0]["inferenceTimestamp"] = "end"
        indexed = by_record(spans(self.export()))
        self.assertEqual(indexed["response:7"]["endTimeUnixNano"], str(timestamp("2026-01-01T00:00:02Z")))
        result["ts"] = "2026-01-01T00:00:02Z"
        self.assertNotIn("call-1", by_record(spans(self.export())))

    def test_json_recovery_exact_numbers_and_incomplete_final_line(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.jsonl"
            header = exact_json(self.session.header).encode() + b"\n"
            path.write_bytes(header + b'{bad}\n' + b'{"type":"gap","id":"g","reason":"unknown"}\n'
                             + b'{"type":"message","id":"m","role":"user","content":[],"_meta":{"com.example":{"n":0.12345678901234567890123,"large":9007199254740999}}}\n'
                             + b'{"type":"gap","id":"incomplete","reason":"unknown"}')
            recovered = read_session(path)
            result = self.export([recovered], include_content=True)
            self.assertEqual([e.data["id"] for e in recovered.entries], ["header", "g", "m"])
            self.assertIn("0.12345678901234567890123", exact_json(result.logs))
            self.assertIn("9007199254740999", exact_json(result.logs))
            self.assertEqual([d["code"] for d in recovered.diagnostics], ["incomplete_tail", "malformed_line"])
            path.write_bytes(header + b'{"type":"gap","type":"message","id":"duplicate-key"}\n' + b'\xff\n')
            self.assertEqual(len(read_session(path).diagnostics), 2)
            path.write_bytes(header + b'{"type":"approval","id":"a","callId":[],"decision":"approved"}\n')
            self.assertEqual(len(read_session(path).diagnostics), 1)

    def test_unresolved_copy_boundary_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.jsonl"
            header = deepcopy(self.child.header)
            header["parent"]["copiedThrough"] = "absent"
            path.write_text(exact_json(header) + "\n" + exact_json(self.child.entries[3].data) + "\n")
            result = self.export([read_session(path)])
            self.assertEqual(len(spans(result)), 1)
            self.assertFalse(any("gen_ai.usage.input_tokens" in attr(x) for x in logs(result)))

    def test_settings_nulls_asks_and_whole_sandbox(self):
        state = {"mode": "edit", "asks": "always", "modelSettings": {"temperature": 0},
                 "externalSandbox": {"kind": "vm", "source": "setting"}}
        update_settings(state, {"modelSettings": {"maxOutputTokens": 0}})
        self.assertEqual(state["modelSettings"], {"temperature": 0, "maxOutputTokens": 0})
        update_settings(state, {"externalSandbox": {"source": "environment"}, "mode": None})
        self.assertNotIn("asks", state)
        self.assertNotIn("mode", state)
        self.assertEqual(state["externalSandbox"], {"source": "environment"})
        update_settings(state, {"modelSettings": None})
        self.assertNotIn("modelSettings", state)

    def test_encrypted_reasoning_has_no_content_even_when_enabled(self):
        message = self.session.entries[3].data
        message["content"] = [{"type": "reasoning", "visibility": "encrypted", "text": "OPAQUE_PRIVATE_STATE"}]
        result = self.export(include_content=True)
        self.assertNotIn("OPAQUE_PRIVATE_STATE", exact_json(result.logs))

    def test_time_parser_offsets_nanoseconds_and_contract_validation(self):
        self.assertEqual(timestamp("2026-01-01T01:00:00.000000001+01:00"), timestamp("2026-01-01T00:00:00Z") + 1)
        for invalid in (None, "no time", "2026-01-01", "2026-02-30T00:00:00Z", "2026-01-01T00:00:00.0000000001Z"):
            self.assertIsNone(timestamp(invalid))
        for invalid in ({}, {"producers": [{}]}, {"producers": [self.contracts["producers"][0]] * 2}):
            with self.assertRaises(ValueError):
                validate_contracts(invalid)
        with self.assertRaisesRegex(ValueError, "duplicate_session"):
            self.export([self.session, self.session])

    def test_repository_samples_and_examples_are_read_as_data(self):
        paths = [*ROOT.glob("samples/*/asr/*.jsonl"),
                 *[p for p in (ROOT / "examples").rglob("*.jsonl") if not p.name.endswith(".annotations.jsonl")]]
        self.assertGreaterEqual(len(paths), 15)
        for path in paths:
            with self.subTest(path=path.relative_to(ROOT)):
                session = read_session(path)
                result = export_sessions([session])
                self.assertGreaterEqual(result.report["logs"], 1)
                self.assertNotIn("asr.record.json", exact_json(result.logs))
                self.assertTrue(all(s["name"] == "invoke_agent" for s in spans(result)))

    def test_fixture_streams_validate_with_node(self):
        for path in FIXTURES.glob("*.jsonl"):
            result = subprocess.run(["node", str(ROOT / "tools/validator/bin/asr-validate.js"), str(path)],
                                    capture_output=True, text=True, cwd=ROOT)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn("0 errors", result.stdout)


if __name__ == "__main__":
    unittest.main()
