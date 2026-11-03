from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from asr_siem import convert, encode_output, read_session
from asr_siem.mapping import milliseconds, reference, update_settings
from asr_siem.reader import json_text

HERE = Path(__file__).parent
ROOT = HERE.parents[2]
OBSERVED = "2026-10-31T00:00:00Z"


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.session = read_session(HERE / "fixtures/audit.jsonl")

    def export(self, **kwargs):
        return convert(self.session, device_uid="synthetic-device", **kwargs)

    def info(self, result, rid):
        return next(e for e in result.events if e["unmapped"]["asr"]["record"].endswith("#" + rid))

    def test_classes_outcomes_and_authorization(self):
        result = self.export()
        self.assertEqual(len(result.events), 16)
        command = self.info(result, "command")
        self.assertEqual((command["class_uid"], command["activity_id"], command["status_id"]), (1007, 1, 0))
        outcome = self.info(result, "command-result")
        self.assertEqual((outcome["activity_id"], outcome["status_id"], outcome["exit_code"]), (99, 1, 0))
        self.assertEqual(command["process"]["uid"], outcome["process"]["uid"])
        self.assertEqual(self.info(result, "proposal")["status_id"], 0)
        self.assertEqual(self.info(result, "write")["unmapped"]["asr"]["actor"], "human")
        self.assertEqual(self.info(result, "write")["class_uid"], 0)
        self.assertIn("actor.identity", self.info(result, "write")["unmapped"]["asr"]["ocsf_missing"])
        decision = self.info(result, "permit")
        self.assertEqual(decision["metadata"]["event_code"], "asr.authorization")
        self.assertEqual(decision["actor"]["authorizations"], [{"decision": "approved"}])
        self.assertEqual(decision["status_id"], 0)
        self.assertEqual(decision["unmapped"]["asr"]["by"], "policy")
        self.assertNotIn("scope", self.info(result, "cancel")["unmapped"]["asr"])
        self.assertEqual(result.report["missing"], ["approvals", "copies", "tool_output"])

    def test_content_default_and_opt_in_effective_input(self):
        result = self.export()
        text = encode_output(result.events) + json_text(result.report)
        for value in ("SYNTHETIC_PRIVATE", "SYNTHETIC_COMMAND", "SYNTHETIC_EFFECTIVE", "SYNTHETIC_OUTPUT", "SYNTHETIC_FILE_CONTENT", "SYNTHETIC_PATCH", "SYNTHETIC_SUBJECT", "SYNTHETIC_QUERY", "SYNTHETIC_GAP_DETAIL"):
            self.assertNotIn(value, text)
        content = self.info(self.export(include_content=True), "command")["unmapped"]["asr"]["content"]
        self.assertEqual(content["effective_input"], "printf SYNTHETIC_EFFECTIVE")
        self.assertEqual(content["inputText"], "printf SYNTHETIC_COMMAND")

    def test_only_observed_network_maps(self):
        result = self.export()
        self.assertEqual([e["class_uid"] for e in result.events if e["class_uid"] >= 4000], [4002, 4001])
        self.session.records[10]["_meta"]["org.agentsessionrecord.siem"]["network"]["observed"] = False
        self.session.records[11].pop("_meta")
        self.assertFalse(any(e["class_uid"] >= 4000 for e in self.export().events))

    def test_copied_prefix_and_individual_copy_get_no_activity_credit(self):
        self.session.records[0]["parent"] = {"session": "com.example.agent:parent", "kind": "fork", "copiedThrough": "write"}
        self.session.records[10]["copiedFrom"] = {"record": "unavailable"}
        result = self.export()
        for rid in ("command", "permit", "write", "http-result"):
            event = self.info(result, rid)
            self.assertEqual(event["class_uid"], 0)
            self.assertFalse(event["unmapped"]["asr"]["credited"])
        self.assertEqual(result.report["unresolved_sessions"], ["com.example.agent:parent"])
        self.assertFalse(any(e["class_uid"] == 4002 for e in result.events))

    def test_ambiguous_call_ids_do_not_pair_approvals_or_effective_input(self):
        call = deepcopy(self.session.records[3])
        call["id"] = "second-command"
        self.session.records.insert(4, call)
        result = self.export(include_content=True)
        self.assertEqual(self.info(result, "permit")["unmapped"]["asr"]["pairing"], "ambiguous")
        info = self.info(result, "command")["unmapped"]["asr"]
        self.assertNotIn("effective_input", info["content"])
        self.assertNotIn("result_record", info)

    def test_missing_time_is_retained_without_inventing_zero_or_export_time(self):
        self.session.records[3].pop("ts")
        result = self.export()
        self.assertEqual(len(result.report["untimed_events"]), 1)
        self.assertNotIn("time", result.report["untimed_events"][0])
        result = self.export(observed_at=OBSERVED)
        event = self.info(result, "command")
        self.assertEqual(event["time"], milliseconds(OBSERVED))
        self.assertEqual(event["unmapped"]["asr"]["time_source"], "explicit_observation")

    def test_device_identity_must_be_supplied(self):
        result = convert(self.session)
        event = self.info(result, "write")
        self.assertEqual(event["class_uid"], 0)
        self.assertEqual(event["unmapped"]["asr"]["mapped_class_uid"], 1001)
        self.assertNotIn("device", event)

    def test_order_is_file_order_and_references_encode_components(self):
        self.session.records[3]["ts"] = "2000-01-01T00:00:00Z"
        result = self.export()
        positions = [e["unmapped"]["asr"]["position"] for e in result.events]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(reference(self.session.records[0]), "com.example.agent:synthetic:audit%3A7")
        header = deepcopy(self.session.records[0])
        header["sessionId"] = "x%# y"
        self.assertTrue(reference(header).endswith("x%25%23%20y"))

    def test_settings_merge_clear_and_invalidation(self):
        state = {}
        update_settings(state, {"mode": "ask", "asks": "always", "sandbox": False, "modelSettings": {"temperature": 0, "maxOutputTokens": 4}})
        update_settings(state, {"mode": "plan", "modelSettings": {"temperature": None}, "externalSandbox": {"kind": "container", "source": "setting"}})
        self.assertNotIn("asks", state)
        self.assertIs(state["sandbox"], False)
        self.assertEqual(state["modelSettings"], {"maxOutputTokens": 4})
        update_settings(state, {"externalSandbox": {}, "modelSettings": None})
        self.assertEqual(state["externalSandbox"], {})
        self.assertNotIn("modelSettings", state)

    def test_recognizable_secrets_are_scrubbed_even_with_content(self):
        fake = "sk-" + "a" * 32
        self.session.records[3]["inputText"] = fake
        self.session.records[5]["input"] = {"api_key": fake, "large": Decimal("9007199254740993.00001")}
        self.session.records[5].pop("inputText")
        text = encode_output(self.export(include_content=True).events)
        self.assertNotIn(fake, text)
        self.assertIn("9007199254740993.00001", text)
        self.assertIn("[redacted]", text)

    def test_recover_lines_duplicate_keys_utf8_and_tail(self):
        raw = (json_text(self.session.records[0]) + '\n{"type":"gap","id":"bad","reason":"unknown","reason":"deleted"}\n').encode()
        raw += b'\xff\n[]\n' + (json_text(self.session.records[-2]) + '\n{"type":"gap"').encode()
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "recovery.jsonl"
            file.write_bytes(raw)
            session = read_session(file)
        self.assertEqual(len(session.records), 2)
        self.assertEqual([d["code"] for d in session.diagnostics].count("malformed_line"), 3)
        self.assertIn("incomplete_tail", [d["code"] for d in session.diagnostics])

    def test_all_repository_asr_samples_and_examples_are_read(self):
        paths = list((ROOT / "examples").rglob("*.jsonl")) + list((ROOT / "samples").glob("*/asr/*.jsonl"))
        paths = [p for p in paths if not p.name.endswith(".annotations.jsonl")]
        self.assertGreaterEqual(len(paths), 16)
        for path in paths:
            with self.subTest(file=path.name):
                result = convert(read_session(path), observed_at=OBSERVED, device_uid="synthetic-device")
                self.assertTrue(result.events)
                for target in ("ocsf", "splunk", "datadog", "elastic"):
                    self.assertTrue(encode_output(result.events, target).endswith("\n"))

    def test_fixture_validates_with_reference_validator(self):
        result = subprocess.run(["node", str(ROOT / "tools/validator/bin/asr-validate.js"), str(HERE / "fixtures/audit.jsonl")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_cli_outputs_owner_only_files_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "audit.ndjson"
            args = ["python3", "-m", "asr_siem", str(HERE / "fixtures/audit.jsonl"), "--output", str(output), "--target", "elastic", "--device-uid", "synthetic-device"]
            first = subprocess.run(args, capture_output=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertEqual(Path(str(output) + ".report.json").stat().st_mode & 0o777, 0o600)
            before = output.read_bytes()
            self.assertNotEqual(subprocess.run(args, capture_output=True).returncode, 0)
            self.assertEqual(output.read_bytes(), before)

    def test_framing_targets_and_invalid_index(self):
        events = self.export().events
        hec = [json.loads(line, parse_float=Decimal) for line in encode_output(events, "splunk").splitlines()]
        self.assertEqual(hec[0]["event"], events[0])
        self.assertEqual(hec[0]["time"], Decimal(events[0]["time"]) / 1000)
        self.assertEqual(len(json.loads(encode_output(events, "datadog"))), len(events))
        bulk = encode_output(events, "elastic").splitlines()
        self.assertEqual(len(bulk), len(events) * 2)
        self.assertEqual(json.loads(bulk[0])["index"]["_id"], events[0]["metadata"]["uid"])
        with self.assertRaises(ValueError):
            encode_output(events, "elastic", index="../bad")

    def test_pinned_ocsf_field_contract_on_samples_and_fixtures(self):
        contract = json.loads((HERE.parent / "ocsf-pin.json").read_text())
        paths = list((ROOT / "examples").rglob("*.jsonl")) + list((ROOT / "samples").glob("*/asr/*.jsonl")) + [HERE / "fixtures/audit.jsonl"]
        for path in paths:
            if path.name.endswith(".annotations.jsonl"):
                continue
            for device_uid in (None, "synthetic-device"):
                for event in convert(read_session(path), observed_at=OBSERVED, device_uid=device_uid).events:
                    rule = contract["classes"][str(event["class_uid"])]
                    self.assertLessEqual(set(rule["required_fields"]), set(event))
                    self.assertLessEqual(set(event), set(rule["allowed_fields"]))
                    self.assertIn(event["activity_id"], rule["activities"])
                    self.assertEqual(event["type_uid"], event["class_uid"] * 100 + event["activity_id"])
                    self.assertEqual(event["category_uid"], event["class_uid"] // 1000)
                    self.assertEqual(event["metadata"]["version"], contract["version"])
                    self.assertEqual(type(event["time"]), int)
                    self.assertIn("name", event["metadata"]["product"])
                    if event["class_uid"] in (1001, 1007):
                        self.assertIn("actor", event)
                        self.assertIn("uid", event["device"])
                        self.assertIn("type_id", event["device"])
                    if event["class_uid"] == 1001:
                        self.assertLessEqual({"name", "type_id"}, set(event["file"]))
                    if event["class_uid"] == 1007:
                        self.assertIn("uid", event["process"])
                    if event["class_uid"] in (4001, 4002):
                        self.assertTrue("src_endpoint" in event or "dst_endpoint" in event)
                    if event["class_uid"] == 4002:
                        self.assertTrue("http_request" in event or "http_response" in event)
                    if event["class_uid"] == 0 and "actor" in event:
                        self.assertIn("host", event["metadata"]["profiles"])

    def test_unknown_data_missing_references_and_future_values(self):
        self.session.records.extend([
            {"type": "com.example.future/event", "id": "future"},
            {"type": "tool_call", "id": "unfinished", "callId": "unfinished", "kind": "_future", "inferenceId": "absent"},
            {"type": "approval", "id": "future-decision", "callId": "absent", "decision": "_future"},
        ])
        result = self.export(observed_at=OBSERVED)
        codes = {d["code"] for d in result.report["diagnostics"]}
        self.assertLessEqual({"unknown_type", "unresolved_inference", "unknown_call_outcome", "unpaired_call_reference"}, codes)
        self.assertEqual(self.info(result, "future-decision")["unmapped"]["asr"]["decision"], "_future")

    def test_encrypted_reasoning_has_no_bytes_or_signatures(self):
        self.session.records[2]["content"] = [{"type": "reasoning", "visibility": "encrypted", "text": "SYNTHETIC_OPAQUE_STATE", "signature": "SYNTHETIC_SIGNATURE"}]
        text = encode_output(self.export(include_content=True).events)
        self.assertNotIn("SYNTHETIC_OPAQUE_STATE", text)
        self.assertNotIn("SYNTHETIC_SIGNATURE", text)

    def test_null_effective_input_and_duplicate_results(self):
        self.session.records[5].pop("inputText")
        self.session.records[5]["input"] = None
        result = self.export(include_content=True)
        self.assertIsNone(self.info(result, "command")["unmapped"]["asr"]["content"]["effective_input"])
        duplicate = deepcopy(self.session.records[5])
        duplicate["id"] = "duplicate-result"
        self.session.records.append(duplicate)
        result = self.export(include_content=True)
        self.assertEqual(self.info(result, "command-result")["unmapped"]["asr"]["pairing"], "ambiguous_results")
        self.assertNotIn("effective_input", self.info(result, "command")["unmapped"]["asr"]["content"])

    def test_invalid_headers_and_copy_boundaries_fail(self):
        self.session.records[0]["parent"] = {"session": "com.example.agent:parent", "kind": "fork", "copiedThrough": "absent"}
        with self.assertRaises(ValueError):
            self.export()
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "bad.jsonl"
            file.write_text('{"type":"session","id":"h","formatVersion":"future"}\n')
            with self.assertRaises(ValueError):
                read_session(file)


if __name__ == "__main__":
    unittest.main()
