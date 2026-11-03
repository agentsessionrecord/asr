"""Envoy ext_proc v3 with buffered request and response bodies."""
from __future__ import annotations

import json
from threading import RLock

from envoy.service.ext_proc.v3 import external_processor_pb2 as pb
from envoy.service.ext_proc.v3 import external_processor_pb2_grpc as rpc

MAX_BODY = 16 * 1024 * 1024


def headers(value):
    return {item.key.lower(): (item.raw_value.decode('utf-8') if item.raw_value else item.value)
            for item in value.headers.headers}


class Processor(rpc.ExternalProcessorServicer):
    def __init__(self, recorder):
        self.recorder = recorder
        self.lock = RLock()

    def Process(self, requests, context):
        request_headers, response_headers = {}, {}
        request_body = response_body = b''
        captured = False
        disabled = False
        try:
            for message in requests:
                field = message.WhichOneof('request')
                try:
                    if field == 'request_headers':
                        request_headers = headers(message.request_headers)
                    elif field == 'response_headers':
                        response_headers = headers(message.response_headers)
                    elif field == 'request_body':
                        if len(request_body) + len(message.request_body.body) > MAX_BODY:
                            disabled = True
                        elif not disabled:
                            request_body += message.request_body.body
                    elif field == 'response_body':
                        if len(response_body) + len(message.response_body.body) > MAX_BODY:
                            disabled = True
                        elif not disabled:
                            response_body += message.response_body.body
                        if message.response_body.end_of_stream and not disabled:
                            path = request_headers.get(':path', '').split('?', 1)[0]
                            api = 'anthropic-messages' if path.endswith('/messages') else 'openai-responses' if path.endswith('/responses') else None
                            with self.lock:
                                self.recorder.capture(api, request_headers, json.loads(request_body), response_body,
                                                      response_headers=response_headers, status=int(response_headers.get(':status', '200')))
                            captured = True
                except Exception:
                    disabled = True
                if disabled:
                    request_body = response_body = b''
                # Empty responses preserve headers and bytes. Body mode is set in Envoy config.
                if field in ('request_headers', 'response_headers'):
                    yield pb.ProcessingResponse(**{field: pb.HeadersResponse()})
                elif field in ('request_body', 'response_body'):
                    yield pb.ProcessingResponse(**{field: pb.BodyResponse()})
                elif field in ('request_trailers', 'response_trailers'):
                    yield pb.ProcessingResponse(**{field: pb.TrailersResponse()})
        except (ValueError, UnicodeError, KeyError, TypeError):
            # Source parse failures are counted without logging raw traffic.
            disabled = True
        finally:
            if not captured and (request_body or disabled):
                with self.lock:
                    self.recorder.skipped += 1
