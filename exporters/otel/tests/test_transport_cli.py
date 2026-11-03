from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from asr_otel import export_sessions, read_session
from asr_otel.__main__ import main
from asr_otel.transport import DeliveryError, local_endpoint, send

FIXTURES = Path(__file__).parent / "fixtures"


@contextmanager
def server(status=200, response=None):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append((self.path, self.headers["Content-Type"],
                          json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            if status == 307:
                self.send_header("Location", "http://192.0.2.1/private")
            self.end_headers()
            self.wfile.write(json.dumps(response or {}).encode())

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}", calls
    finally:
        httpd.shutdown()
        worker.join()
        httpd.server_close()


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.result = export_sessions([read_session(FIXTURES / "session.jsonl")])

    def test_otlp_http_json_both_paths_and_proxies_disabled(self):
        with server() as (endpoint, calls), patch.dict(os.environ, {"http_proxy": "http://192.0.2.1:1", "no_proxy": ""}):
            self.assertEqual(send(self.result, endpoint), ["traces", "logs"])
        self.assertEqual([call[0] for call in calls], ["/v1/traces", "/v1/logs"])
        self.assertTrue(all(call[1] == "application/json" for call in calls))
        self.assertEqual(calls[0][2], self.result.traces)
        self.assertEqual(calls[1][2], self.result.logs)

    def test_endpoint_restrictions_and_ipv6(self):
        self.assertEqual(local_endpoint("http://[::1]:4318/"), "http://[::1]:4318")
        for value in ("http://localhost:4318", "http://192.0.2.1", "http://127.0.0.1.example.com", "file:///tmp/out",
                      "http://user@127.0.0.1", "http://127.0.0.1?target=remote", "http://127.0.0.1#fragment",
                      "http://127.0.0.1:999999", "http://[::1%25eth0]", "http://127.0.0.1/\ninvalid"):
            with self.subTest(value=value), self.assertRaises(DeliveryError):
                local_endpoint(value)

    def test_http_failures_redirects_and_partial_success_are_failures(self):
        for status, response, code in ((503, {}, "traces_http_503"), (307, {}, "traces_http_307"),
                                       (200, {"partialSuccess": {"rejectedSpans": "1", "errorMessage": "private"}}, "traces_partial_success"),
                                       (200, {"partialSuccess": []}, "traces_invalid_response")):
            with self.subTest(status=status, response=response), server(status, response) as (endpoint, calls):
                with self.assertRaisesRegex(DeliveryError, code):
                    send(self.result, endpoint)
                self.assertEqual(len(calls), 1)

    def test_log_rejections_are_not_silently_accepted(self):
        self.result.traces["resourceSpans"] = []
        with server(response={"partialSuccess": {"rejectedLogRecords": "2"}}) as (endpoint, _):
            with self.assertRaisesRegex(DeliveryError, "logs_partial_success"):
                send(self.result, endpoint)


class CliTests(unittest.TestCase):
    def test_cli_writes_private_deterministic_files_and_can_send(self):
        with tempfile.TemporaryDirectory() as directory, server() as (endpoint, calls):
            target = Path(directory) / "output"
            command = [sys.executable, "-m", "asr_otel", str(FIXTURES / "session.jsonl"),
                       "--contracts", str(FIXTURES / "contracts.json"), "--output", str(target), "--endpoint", endpoint]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("spans=4", result.stdout)
            self.assertEqual(len(calls), 2)
            before = {p.name: p.read_bytes() for p in target.iterdir()}
            for path in target.iterdir():
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(target.stat().st_mode & 0o777, 0o700)
            self.assertEqual(main(command[3:]), 0)
            self.assertEqual(before, {p.name: p.read_bytes() for p in target.iterdir()})

    def test_cli_preserves_files_on_delivery_failure_and_hides_response_body(self):
        with tempfile.TemporaryDirectory() as directory, server(403, {"error": "SYNTHETIC_PRIVATE"}) as (endpoint, _):
            result = subprocess.run([sys.executable, "-m", "asr_otel", str(FIXTURES / "session.jsonl"),
                                     "--output", directory, "--endpoint", endpoint], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("traces_http_403", result.stderr)
            self.assertNotIn("SYNTHETIC_PRIVATE", result.stderr)
            self.assertTrue((Path(directory) / "logs.json").is_file())

    def test_cli_refuses_to_replace_input_and_rejects_invalid_options(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "traces.json"
            original = (FIXTURES / "session.jsonl").read_bytes()
            source.write_bytes(original)
            self.assertEqual(main([str(source), "--output", directory]), 1)
            self.assertEqual(source.read_bytes(), original)
            with self.assertRaises(SystemExit):
                main([str(source), "--output", directory, "--timeout", "nan"])


if __name__ == "__main__":
    unittest.main()
