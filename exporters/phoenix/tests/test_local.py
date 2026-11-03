from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

import pytest

from asr_phoenix.local import load, local_url


@pytest.mark.parametrize("url", ["https://127.0.0.1:6006", "http://example.com", "http://localhost:6006", "http://127.0.0.1@evil.example", "http://127.0.0.1:6006/path", "http://127.0.0.1:6006?redirect=1", "http://127.0.0.2:6006"])
def test_only_literal_loopback_origin_is_allowed(url):
    with pytest.raises(ValueError):
        local_url(url)


def test_loader_does_not_buffer_response_bodies(tmp_path, monkeypatch):
    class Response:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, *args):
            raise AssertionError('response body must not be buffered')
    class Opener:
        def open(self, *args, **kwargs):
            return Response()
    monkeypatch.setattr('asr_phoenix.local.build_opener', lambda *args: Opener())
    (tmp_path / 'traces.otlp.pb').write_bytes(b'synthetic')
    (tmp_path / 'dataset-upload.json').write_text('{}')
    assert load('http://127.0.0.1:6006', tmp_path) == [200, 200]


def test_loader_sends_expected_files_and_ignores_proxy_environment(tmp_path, monkeypatch):
    received = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append((self.path, self.headers["Content-Type"], self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.end_headers()
        def log_message(self, *args):
            pass
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("http_proxy", "http://untrusted.example:9")
    (tmp_path / "traces.otlp.pb").write_bytes(b"synthetic")
    (tmp_path / "dataset-upload.json").write_text("{}")
    try:
        assert load(f"http://127.0.0.1:{server.server_port}", tmp_path) == [200, 200]
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
    assert received == [("/v1/traces", "application/x-protobuf", b"synthetic"), ("/v1/datasets/upload", "application/json", b"{}")]


def test_loader_refuses_redirects(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(307)
            self.send_header("Location", "http://untrusted.example/")
            self.end_headers()
        def log_message(self, *args):
            pass
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    (tmp_path / "traces.otlp.pb").write_bytes(b"synthetic")
    try:
        with pytest.raises(ValueError, match="redirect_refused"):
            load(f"http://127.0.0.1:{server.server_port}", tmp_path)
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
