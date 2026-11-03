"""Loopback-only native logging receivers and Envoy external processor."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import signal

from .core import GatewayRecorder

MAX_BODY = 16 * 1024 * 1024


def handler(recorder, adapter, paths):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.connection.settimeout(10)
            if self.path not in paths:
                self.send_error(404)
                return
            try:
                size = int(self.headers.get('content-length', '0'))
                if not 0 < size <= MAX_BODY:
                    raise ValueError('Body size')
                payload = json.loads(self.rfile.read(size))
                accepted = adapter(recorder, payload, headers=dict(self.headers), path=self.path)
            except (ValueError, KeyError, TypeError, UnicodeError):
                self.send_error(422, 'ASR_INVALID_NATIVE_LOG')
                return
            self.send_response(200 if accepted else 422)
            self.end_headers()
            self.wfile.write(b'{"accepted":true}' if accepted else b'{"accepted":false}')
    return Handler


def entry(name, adapter, paths):
    parser = argparse.ArgumentParser(description=f'Local {name} ASR receiver')
    parser.add_argument('--output', required=True)
    parser.add_argument('--port', type=int, default=8421)
    parser.add_argument('--input', help='Offline JSONL fixtures with payload, headers and path')
    args = parser.parse_args()
    recorder = GatewayRecorder(args.output, gateway=name, historical=bool(args.input))
    try:
        if args.input:
            with Path(args.input).open() as stream:
                for line in iter(lambda: stream.readline(MAX_BODY + 1), ''):
                    if len(line) > MAX_BODY:
                        raise ValueError('Native log frame exceeds byte limit')
                    event = json.loads(line)
                    adapter(recorder, event['payload'], event.get('headers', {}), event.get('path', paths[0]))
        else:
            server = HTTPServer(('127.0.0.1', args.port), handler(recorder, adapter, paths))
            server.timeout = 0.5
            running = True
            def stop(*_):
                nonlocal running
                running = False
            signal.signal(signal.SIGTERM, stop)
            signal.signal(signal.SIGINT, stop)
            try:
                while running:
                    server.handle_request()
            finally:
                server.server_close()
    finally:
        recorder.close()
    print(json.dumps({'accepted': recorder.accepted, 'skipped': recorder.skipped}))
    if recorder.skipped:
        raise SystemExit(1)


def main():
    import grpc
    from envoy.service.ext_proc.v3 import external_processor_pb2_grpc as rpc
    from .envoy import Processor

    parser = argparse.ArgumentParser(description='Envoy ext_proc v3 ASR recorder')
    parser.add_argument('--output', required=True)
    parser.add_argument('--port', type=int, default=8420)
    args = parser.parse_args()
    recorder = GatewayRecorder(args.output)
    server = grpc.server(ThreadPoolExecutor(max_workers=4), options=[('grpc.max_receive_message_length', MAX_BODY)])
    rpc.add_ExternalProcessorServicer_to_server(Processor(recorder), server)
    if not server.add_insecure_port(f'127.0.0.1:{args.port}'):
        raise SystemExit('ASR_BIND_FAILED')
    server.start()
    def stop(*_):
        server.stop(2)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.wait_for_termination()
    finally:
        server.stop(0).wait()
        recorder.close()
