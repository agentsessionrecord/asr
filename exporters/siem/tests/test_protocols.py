from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import json
import os
from pathlib import Path
import threading
import unittest
from urllib.parse import urlsplit
import uuid

from asr_siem import convert, encode_output, read_session

HERE = Path(__file__).parent


class HecTests(unittest.TestCase):
    def test_local_hec_request_matches_recorded_synthetic_fixture(self):
        fixture = json.loads((HERE / "fixtures/hec-request.json").read_text())
        events = convert(read_session(HERE / "fixtures/audit.jsonl"), device_uid="synthetic-device").events
        body = encode_output(events[:1], "splunk").encode()
        captured = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                captured.append({"method": self.command, "path": self.path,
                                 "content_type": self.headers["Content-Type"],
                                 "body": self.rfile.read(int(self.headers["Content-Length"])).decode()})
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"text":"Success","code":0}')

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection(*server.server_address, timeout=5)
        try:
            connection.request("POST", "/services/collector/event", body, {"Content-Type": "application/json"})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read())["code"], 0)
            self.assertEqual(captured, [fixture])
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


@unittest.skipUnless(os.environ.get("ASR_SIEM_OPENSEARCH_URL"), "local OpenSearch URL not configured")
class OpenSearchTests(unittest.TestCase):
    def test_bulk_mapping_queries_and_idempotent_reload(self):
        endpoint = urlsplit(os.environ["ASR_SIEM_OPENSEARCH_URL"])
        self.assertEqual(endpoint.scheme, "http")
        self.assertIn(endpoint.hostname, ("127.0.0.1", "localhost", "::1"))
        self.assertIsNone(endpoint.username)
        self.assertIsNone(endpoint.password)
        self.assertIn(endpoint.path, ("", "/"))
        index = "asr-siem-test-" + uuid.uuid4().hex
        connection = http.client.HTTPConnection(endpoint.hostname, endpoint.port, timeout=20)

        def request(method, path, body=None, content_type="application/json"):
            connection.request(method, path, body, {"Content-Type": content_type})
            response = connection.getresponse()
            raw = response.read()
            self.assertLess(response.status, 300, "local_api_error")
            return json.loads(raw)

        events = convert(read_session(HERE / "fixtures/audit.jsonl"), device_uid="synthetic-device").events
        try:
            mapping = (HERE.parent / "elastic-mapping.json").read_bytes()
            request("PUT", "/" + index, mapping)
            body = encode_output(events, "elastic", index=index).encode()
            for _ in range(2):
                result = request("POST", "/_bulk?refresh=true", body, "application/x-ndjson")
                self.assertFalse(result["errors"])
                self.assertTrue(all(item["index"]["status"] in (200, 201) for item in result["items"]))
            self.assertEqual(request("GET", "/" + index + "/_count")["count"], len(events))
            query = json.dumps({"query": {"term": {"metadata.event_code": "asr.authorization"}}, "sort": [{"unmapped.asr.position": "asc"}]}).encode()
            hits = request("POST", "/" + index + "/_search", query)["hits"]
            self.assertEqual(hits["total"]["value"], 2)
            self.assertEqual(hits["hits"][0]["_source"]["unmapped"]["asr"]["by"], "policy")
            self.assertEqual(request("GET", "/" + index + "/_mapping")[index]["mappings"]["properties"]["time"]["type"], "date")
        finally:
            try:
                request("DELETE", "/" + index)
            finally:
                connection.close()
