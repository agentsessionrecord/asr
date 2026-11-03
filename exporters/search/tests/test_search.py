from contextlib import redirect_stderr, redirect_stdout
from decimal import Decimal
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))

from asr_search.bundle import export, mapping, read_jsonl, verify_bundle
from asr_search.cli import main
from asr_search.documents import Catalog, chunks, documents, update_settings
from asr_search.reader import SearchError, citation, dumps, loads, read_stream
from asr_search.transport import LocalHTTP, embed, load_qdrant, load_search


FIXTURE = PACKAGE / "tests/fixtures/search.jsonl"
HEADER = {"type": "session", "id": "header", "formatVersion": "0.1",
          "agent": {"name": "com.example.search"}, "sessionId": "synthetic",
          "producer": {"name": "synthetic-fixture", "version": "1.0", "method": "native"}}


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="asr-search-test-")
        self.addCleanup(self.temporary.cleanup)
        self.scratch = Path(self.temporary.name)

    def stream(self, records, header=None, tail=b""):
        path = self.scratch / "input.jsonl"
        path.write_bytes(("\n".join(dumps(r) for r in [header or HEADER, *records]) + "\n").encode() + tail)
        return path

    def project(self, path):
        stream = read_stream(path)
        catalog = Catalog()
        catalog.add(stream)
        return documents(stream, catalog)

    def test_fixture_credit_effective_input_missing_and_settings(self):
        docs = self.project(FIXTURE)
        by_id = {d["record_id"]: d for d in docs}
        self.assertFalse(by_id["inherited-call"]["credit_eligible"])
        self.assertTrue(by_id["own-call"]["credit_eligible"])
        self.assertEqual(by_id["own-call"]["usage"]["inputTokens"], 0)
        self.assertEqual(loads(by_id["own-call"]["cost_json"])["amount"], 0)
        self.assertEqual(by_id["read"]["call_outcome"], "completed")
        self.assertEqual(loads(by_id["read"]["effective_input_json"]), "")
        self.assertEqual(by_id["read"]["resolved_paths"], ["/work/search/src/parser.py"])
        self.assertEqual(by_id["read"]["known_missing"], ["approvals", "timestamps"])
        final = loads(docs[0]["final_agent_settings_json"])
        self.assertNotIn("asks", final)
        self.assertEqual(final["modelSettings"], {"temperature": 0})
        self.assertEqual(final["externalSandbox"], {})
        self.assertEqual(loads(docs[0]["session_usage_json"])["inputTokens"], 900)
        self.assertEqual(sum(d.get("usage", {}).get("inputTokens", 0) for d in docs
                             if d["record_type"] == "inference" and d["credit_eligible"]), 0)
        self.assertEqual(by_id["gap"]["gap_reason"], "redacted")
        self.assertIn("com.example.search:unavailable", docs[0]["unresolved_refs"])

    def test_copy_source_unknown_still_gets_no_credit(self):
        path = self.stream([{"type": "inference", "id": "copied", "model": {"requested": "synthetic"},
                             "copiedFrom": {"record": "unknown"}, "usage": {"outputTokens": 8}}])
        doc = self.project(path)[1]
        self.assertFalse(doc["credit_eligible"])
        self.assertIn("copy_record:unknown", doc["unresolved_refs"])

    def test_ambiguous_calls_never_pair_by_proximity(self):
        path = self.stream([
            {"type": "tool_call", "id": "a", "callId": "shared", "name": "a"},
            {"type": "tool_result", "id": "result", "callId": "shared", "status": "completed"},
            {"type": "approval", "id": "approval", "callId": "shared", "decision": "approved"},
            {"type": "tool_call", "id": "b", "callId": "shared", "name": "b"},
        ])
        docs = self.project(path)
        self.assertTrue(all("paired_call" not in d for d in docs[1:]))
        self.assertEqual(docs[1]["call_outcome"], "unknown")
        self.assertEqual(docs[2]["pairing"], "unpaired")
        self.assertEqual(docs[3]["pairing"], "unpaired")

    def test_forward_unique_pair_and_no_status_from_exit_code(self):
        path = self.stream([
            {"type": "tool_result", "id": "r", "callId": "x", "status": "unknown", "exec": {"exitCode": 0}},
            {"type": "tool_call", "id": "c", "callId": "x", "name": "shell"},
            {"type": "tool_call", "id": "no-result", "callId": "y", "name": "shell"},
            {"type": "tool_result", "id": "orphan", "status": "completed"},
        ])
        docs = self.project(path)
        self.assertEqual(docs[1]["paired_call"], "com.example.search:synthetic#c")
        self.assertEqual(docs[2]["call_outcome"], "unknown")
        self.assertEqual(docs[3]["call_outcome"], "unknown")
        self.assertEqual(docs[4]["pairing"], "unpaired")

    def test_recovery_file_order_and_exact_numbers(self):
        path = self.stream([])
        raw = ('{"type":"com.example.search/event","id":"first","ts":"2026-01-02T00:00:00Z",'
               '"_meta":{"com.example.search":{"number":900719925474099312345,"decimal":1.2300000000000000001}}}')
        with path.open("ab") as target:
            target.write(raw.encode() + b"\nnot json\n")
            target.write(b'{"type":"message","id":"bad","id":"duplicate"}\n')
            target.write(b'{"type":"message","id":"utf8","content":"\xff"}\n')
            target.write(b'{"type":"message","id":"later","ts":"2026-01-01T00:00:00Z","role":"user","content":[]}\n')
            target.write(b'{"type":"message","id":"tail","role":"user","content":[]}')
        stream = read_stream(path)
        self.assertEqual([r.record["id"] for r in stream.rows], ["header", "first", "later"])
        self.assertEqual(stream.rows[1].raw, raw)
        self.assertEqual(len(stream.issues), 4)
        self.assertEqual(stream.issues[-1]["code"], "incomplete_tail")
        values = loads(dumps(stream.rows[1].record))["_meta"]["com.example.search"]
        self.assertEqual(values["number"], 900719925474099312345)
        self.assertEqual(values["decimal"], Decimal("1.2300000000000000001"))
        self.assertEqual(self.project(path)[2]["position"], 6)

    def test_large_line_recovers_without_using_incomplete_tail(self):
        path = self.stream([])
        with path.open("ab") as out:
            out.write(b"x" * 1024 + b"\n")
            out.write(b'{"type":"gap","id":"g","reason":"unknown"}\n')
            out.write(b"x" * 1024)
        stream = read_stream(path, max_line_bytes=512)
        self.assertEqual([r.record["id"] for r in stream.rows], ["header", "g"])
        self.assertEqual([i["code"] for i in stream.issues], ["line_too_large", "incomplete_tail"])

    def test_bad_header_boundary_and_duplicate_identity_fail(self):
        path = self.stream([], {**HEADER, "formatVersion": "9"})
        with self.assertRaisesRegex(SearchError, "unsupported_format"):
            read_stream(path)
        path = self.stream([], {**HEADER, "parent": {"session": "com.example.search:p", "kind": "fork",
                                                     "copiedThrough": "absent"}})
        with self.assertRaisesRegex(SearchError, "copied_boundary"):
            read_stream(path)
        with self.assertRaisesRegex(SearchError, "duplicate_session"):
            export([FIXTURE, FIXTURE], self.scratch / "duplicate")

    def test_unknown_fields_and_types_are_retained_without_interpretation(self):
        path = self.stream([
            {"type": "com.example.search/event", "id": "vendor", "subagent": "unfamiliar",
             "callId": {"future": 1}, "model": "unfamiliar"},
            {"type": "message", "id": "m", "role": "user", "content": [], "exec": "unfamiliar"},
            {"type": "message", "id": "bad", "role": "user", "content": "invalid"},
            {"type": "gap", "id": "bad-gap"},
            {"type": "gap", "id": "g", "reason": "unknown"},
        ])
        docs = self.project(path)
        self.assertEqual([d["record_id"] for d in docs], ["header", "vendor", "m", "g"])
        self.assertIn('"subagent":"unfamiliar"', docs[1]["raw_json"])
        self.assertEqual(docs[1]["text"], [])
        self.assertEqual(docs[0]["reader_issues"], [{"position": 4, "code": "invalid_record_shape"},
                                                 {"position": 5, "code": "invalid_record_shape"}])

    def test_settings_nulls_and_repeated_policy_keep_the_correct_facts(self):
        current = {"mode": "ask", "asks": "always", "modelSettings": {"temperature": 0},
                   "externalSandbox": {"kind": "container"}}
        self.assertEqual(update_settings(current, {"mode": "ask"})["asks"], "always")
        changed = update_settings(current, {"mode": "code", "modelSettings": None, "externalSandbox": None})
        self.assertEqual(changed, {"mode": "code"})
        self.assertEqual(current["modelSettings"], {"temperature": 0})

    def test_reference_encoding_and_unresolved_inference(self):
        path = self.stream([{"type": "message", "id": "m #:%", "role": "assistant", "content": [],
                             "inferenceId": "not known"}], {**HEADER, "sessionId": "a:b# %\t", "namespace": "n:s"})
        doc = self.project(path)[1]
        self.assertEqual(doc["citation"], "com.example.search:n%3As:a%3Ab%23%20%25%09#m%20%23%3A%25")
        self.assertEqual(doc["unresolved_refs"], ["com.example.search:n%3As:a%3Ab%23%20%25%09#not%20known"])

    def test_relationships_combine_both_sides_and_one_side(self):
        paths = [ROOT / "examples/subagent/parent.jsonl", ROOT / "examples/subagent/child.jsonl"]
        catalog = Catalog()
        streams = [read_stream(p) for p in paths]
        for stream in streams:
            catalog.add(stream)
        for stream in streams:
            doc = documents(stream, catalog)[0]
            self.assertEqual(len(doc["relationships"]), 1)
            self.assertEqual(len(doc["relationships"][0]["evidence"]), 3)
            self.assertEqual(doc["unresolved_refs"], [])
        catalog = Catalog()
        catalog.add(streams[1])
        doc = documents(streams[1], catalog)[0]
        self.assertEqual(len(doc["relationships"]), 1)
        self.assertTrue(doc["unresolved_refs"])

    def test_chunks_preserve_part_order_offsets_and_overrides(self):
        doc = self.project(FIXTURE)[4]
        pieces = list(chunks(doc, 10, 3))
        self.assertTrue(pieces)
        for piece in pieces:
            self.assertEqual(piece["text"], doc["text_fields"][0]["text"][piece["start"]:piece["end"]])
            self.assertEqual(piece["author"], "human")
            self.assertEqual(piece["origin"], "prompt")
        self.assertEqual(pieces, list(chunks(doc, 10, 3)))
        self.assertEqual(pieces[1]["start"], 7)
        self.assertNotIn("author", doc)
        with self.assertRaises(SearchError):
            list(chunks(doc, 10, 10))

    def test_untrusted_text_never_executes_fetches_or_indexes_unknown_parts(self):
        path = self.stream([{"type": "message", "id": "m", "role": "user", "content": [
            {"type": "text", "text": "touch /tmp/asr-never-run"},
            {"type": "resource_link", "uri": "http://127.0.0.1:1/untrusted", "name": "link"},
            {"type": "resource", "resource": {"uri": "file:///work/not-read", "text": "embedded only"}},
            {"type": "reasoning", "visibility": "encrypted", "text": "never-index-encrypted"},
            {"type": "future_part", "text": "unknown-only-raw"},
        ]}])
        with patch("subprocess.run") as run, patch("socket.create_connection") as connect:
            bundle = self.scratch / "safe"
            export([path], bundle)
            run.assert_not_called()
            connect.assert_not_called()
        doc = list(read_jsonl(bundle / "documents.jsonl"))[1]
        self.assertEqual(doc["text"], ["touch /tmp/asr-never-run", "embedded only"])
        self.assertIn("unknown-only-raw", doc["raw_json"])

    def test_samples_examples_and_fixture_validate_and_export(self):
        paths = sorted((ROOT / "samples").glob("*/asr/*.jsonl"))
        paths += sorted(p for p in (ROOT / "examples").rglob("*.jsonl") if not p.name.endswith(".annotations.jsonl"))
        paths.append(FIXTURE)
        self.assertGreaterEqual(len(paths), 16)
        validator = ROOT / "tools/validator/bin/asr-validate.js"
        warning_codes = {}
        warnings = 0
        for n, path in enumerate(paths):
            result = subprocess.run(["node", str(validator), "--json", "--summary", str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, f"validator failed on input {n}")
            validation = json.loads(result.stdout)
            self.assertEqual(validation["errors"], 0)
            warnings += validation["warnings"]
            for code, count in validation["counts"].items():
                warning_codes[code] = warning_codes.get(code, 0) + count
            bundle = self.scratch / f"bundle-{n}"
            manifest = export([path], bundle)
            self.assertEqual(verify_bundle(bundle), manifest)
            bulk = list(read_jsonl(bundle / "bulk.ndjson"))
            docs = list(read_jsonl(bundle / "documents.jsonl"))
            self.assertEqual(bulk[1::2], docs)
            self.assertEqual([r.raw for r in read_stream(path).rows], [d["raw_json"] for d in docs])
        self.assertGreater(warnings, 0)
        print(json.dumps({"validation_inputs": len(paths), "validation_errors": 0,
                          "validation_warnings": warnings, "warning_codes": warning_codes}), flush=True)

    def test_embeddings_and_integrity_atomic_failure(self):
        bundle = self.scratch / "vectors"
        command = [sys.executable, str(PACKAGE / "tests/fixture_embedder.py")]
        manifest = export([FIXTURE], bundle, embedding_command=command, dimensions=3,
                          embedding_model="synthetic-counts-v1")
        rows = list(read_jsonl(bundle / "chunks.jsonl"))
        self.assertEqual(len(rows), manifest["counts"]["chunks"])
        self.assertTrue(all(len(row["vector"]) == 3 for row in rows))
        self.assertNotIn("embedding_command", dumps(manifest))
        (bundle / "chunks.jsonl").write_text("changed\n")
        with self.assertRaisesRegex(SearchError, "integrity"):
            verify_bundle(bundle)
        with self.assertRaisesRegex(SearchError, "already_exists"):
            export([FIXTURE], bundle)
        with patch("asr_search.transport.subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", "private")):
            with self.assertRaisesRegex(SearchError, "embedding_command_failed"):
                export([FIXTURE], self.scratch / "failed", embedding_command=command,
                       dimensions=3, embedding_model="synthetic")
        self.assertFalse((self.scratch / "failed").exists())
        self.assertEqual(list(self.scratch.glob(".asr-search-*")), [])

    def test_bad_embeddings_rejected(self):
        for value in ([], [[1, 2]], [[True, 2, 3]], [["1", 2, 3]], [[1, None, 3]]):
            with self.subTest(value=value), patch("asr_search.transport.subprocess.run",
                    return_value=subprocess.CompletedProcess([], 0, json.dumps({"vectors": value}), "")):
                with self.assertRaisesRegex(SearchError, "invalid_embedding_response"):
                    embed(["explicit-command"], ["synthetic"], 3)
        with self.assertRaisesRegex(SearchError, "argv"):
            embed("shell command", [], 3)

    def test_local_endpoints_only(self):
        for endpoint in ("https://example.com", "http://127.0.0.1@evil.example", "file:///work/data",
                         "http://127.0.0.1/path", "http://127.0.0.1?redirect=1", "http://0.0.0.0",
                         "http://[::ffff:192.0.2.1]", "http://127.0.0.1:bad", "http://127.0.0.1#fragment"):
            with self.subTest(endpoint=endpoint), self.assertRaises(SearchError):
                LocalHTTP(endpoint)
        for endpoint in ("http://127.0.0.1:9200", "http://localhost:6333/", "http://[::1]:6333"):
            LocalHTTP(endpoint)

    def test_cli_errors_never_print_source_or_command_output(self):
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = main(["export", str(FIXTURE), "--output", str(self.scratch / "out"), "--index", "bad/path"])
        self.assertEqual(code, 1)
        self.assertEqual(stderr.getvalue(), "asr-search: invalid_index_or_collection_name\n")
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(main(["export", str(FIXTURE), "--output", str(self.scratch / "out")]), 0)
        self.assertIn("counts", loads(stdout.getvalue()))
        self.assertNotIn("quokka", stdout.getvalue())


class FakeHTTP:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []

    def request(self, *args, **kwargs):
        self.requests.append((args, kwargs))
        return next(self.replies)


class LoaderTests(unittest.TestCase):
    def test_search_batches_and_partial_errors(self):
        client = FakeHTTP([(404, {}), (200, {}), (200, {"errors": False, "items": [{"index": {"status": 201}}]}),
                           (200, {"errors": False, "items": [{"index": {"status": 200}}]}), (200, {})])
        self.assertEqual(load_search(client, "synthetic", mapping(), [{"document_id": "a"}, {"document_id": "b"}], 1), 2)
        body = client.requests[2][0][2]
        self.assertTrue(body.endswith(b"\n"))
        self.assertEqual(loads(body.splitlines()[0])["index"]["_index"], "synthetic")
        for response in ({"errors": True, "items": [{"index": {"status": 400}}]},
                         {"errors": False, "items": []}, {"errors": False, "items": [{"index": {"status": 429}}]}):
            client = FakeHTTP([(404, {}), (200, {}), (200, response)])
            with self.assertRaisesRegex(SearchError, "bulk_item_failure"):
                load_search(client, "synthetic", mapping(), [{"document_id": "a"}])

    def test_existing_mapping_dimension_mismatch_and_oversized_documents(self):
        client = FakeHTTP([(200, {"synthetic": {"mappings": {}}})])
        with self.assertRaisesRegex(SearchError, "mapping_differs"):
            load_search(client, "synthetic", mapping(), [])
        client = FakeHTTP([(404, {}), (200, {})])
        with self.assertRaisesRegex(SearchError, "byte_limit"):
            load_search(client, "synthetic", mapping(), [{"document_id": "a", "text": "x" * 100}], max_batch_bytes=100)
        client = FakeHTTP([(200, {"result": {"config": {"params": {"vectors": {"size": 5, "distance": "Cosine"}}}}})])
        with self.assertRaisesRegex(SearchError, "vectors_differ"):
            load_qdrant(client, "synthetic", 3, [])

    def test_qdrant_payload_and_waited_upserts(self):
        client = FakeHTTP([(404, {}), (200, {}), (200, {"result": {"status": "completed"}})])
        chunk = {"chunk_id": "00000000-0000-5000-8000-000000000001", "vector": [1, 2, 3], "citation": "synthetic#r"}
        self.assertEqual(load_qdrant(client, "synthetic", 3, [chunk]), 1)
        args = client.requests[-1][0]
        self.assertIn("wait=true", args[1])
        self.assertEqual(args[2]["points"][0]["payload"], {k: v for k, v in chunk.items() if k != "vector"})


if __name__ == "__main__":
    unittest.main()
