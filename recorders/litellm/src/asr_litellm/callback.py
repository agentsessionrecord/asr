"""LiteLLM custom logger for native HTTP pass-through routes."""
from __future__ import annotations

import atexit
from contextvars import ContextVar
from functools import wraps
import json
import logging
import os

import httpx
from litellm.integrations.custom_logger import CustomLogger

from .recorder import MAX_BYTES, Recorder

LOG = logging.getLogger(__name__)
LOG.addHandler(logging.NullHandler())


def passive_hook(method):
    @wraps(method)
    async def observe(self, *args, **kwargs):
        try:
            await method(self, *args, **kwargs)
        except Exception:
            self.failure()
        return None
    return observe


class ObservedStream(httpx.AsyncByteStream):
    """Forward each original chunk, even when capture or finalization fails."""
    def __init__(self, source, exchange, *, stream=True):
        self.source, self.exchange, self.stream = source, exchange, stream
        self.disabled = False
        self.buffer = bytearray()
        self.finished = False

    def call(self, method, *args, **kwargs):
        if self.disabled:
            return
        try:
            getattr(self.exchange, method)(*args, **kwargs)
        except Exception:
            self.disabled = True
            self.buffer.clear()
            LOG.warning("ASR stream observation failed")
            try:
                self.exchange.disable()
            except Exception:
                pass

    def finish(self, error=False):
        if self.finished:
            return
        self.finished = True
        if self.stream or error:
            self.call('finish', stream=self.stream, error=error)
        elif not self.disabled:
            try:
                value = json.loads(self.buffer)
            except Exception:
                self.call('finish', stream=False, error=True)
            else:
                self.call('json', value)
        self.buffer.clear()

    async def __aiter__(self):
        complete = False
        try:
            async for chunk in self.source:
                try:
                    if self.stream:
                        self.call('feed', chunk)
                    elif not self.disabled:
                        if len(self.buffer) + len(chunk) > MAX_BYTES:
                            self.call('disable')
                            self.disabled = True
                            self.buffer.clear()
                        else:
                            self.buffer.extend(chunk)
                except Exception:
                    self.call('disable')
                    self.disabled = True
                    self.buffer.clear()
                yield chunk
            complete = True
        finally:
            self.finish(error=not complete)

    async def aclose(self):
        try:
            await self.source.aclose()
        finally:
            self.finish(error=True)


class ASRLogger(CustomLogger):
    """Observe native responses. Recorder errors never reject proxy requests."""
    def __init__(self, directory=None):
        super().__init__()
        self.directory = directory
        self._recorder = None
        self.failures = 0
        self._snapshot = ContextVar('asr_litellm_request', default=None)
        atexit.register(self.close)

    def failure(self):
        self.failures += 1
        LOG.warning("ASR callback observation failed")

    @property
    def recorder(self):
        if self._recorder is None:
            directory = self.directory or os.environ.get('ASR_OUTPUT_DIR')
            if not directory:
                return None
            self._recorder = Recorder(directory)
        return self._recorder

    @passive_hook
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        self._snapshot.set(None)
        if call_type == 'pass_through_endpoint':
            recorder = self.recorder
            if recorder is None:
                self.failure()
                return
            fields = ('model', 'messages', 'system', 'input', 'instructions', 'tools', 'metadata', 'prompt_cache_key',
                      'previous_response_id', 'max_tokens', 'max_output_tokens', 'reasoning', 'output_config',
                      'temperature', 'service_tier', 'stream', 'top_p', 'parallel_tool_calls')
            snapshot = {key: data[key] for key in fields if key in data}
            if len(json.dumps(snapshot).encode()) > MAX_BYTES:
                self.failure()
                return
            self._snapshot.set((snapshot, recorder.clock()))

    @passive_hook
    async def async_post_call_response_headers_hook(self, data, user_api_key_dict, response,
                                                   request_headers=None, litellm_call_info=None):
        snapshot = self._snapshot.get()
        self._snapshot.set(None)
        if not isinstance(response, httpx.Response):
            return
        path = response.request.url.path.rstrip('/')
        api = 'anthropic-messages' if path.endswith('/messages') else 'openai-responses' if path.endswith('/responses') else None
        if api is None:
            return
        recorder = self.recorder
        if recorder is None:
            self.failure()
            return
        upstream_headers = dict(response.request.headers)
        headers = {**upstream_headers, **dict(request_headers or {})}
        raw = None if snapshot else response.request.content
        if raw is not None and len(raw) > MAX_BYTES:
            self.failure()
            recorder.note_loss(api, headers)
            return
        try:
            body = snapshot[0] if snapshot else json.loads(raw)
        except Exception:
            self.failure()
            recorder.note_loss(api, headers)
            return
        from .privacy import Scrubber
        secrets = Scrubber(upstream_headers, dict(request_headers or {})).secrets
        exchange = recorder.start(api, headers, body, response_headers=dict(response.headers),
                                  status=response.status_code, secrets=secrets, started_at=snapshot[1] if snapshot else None)
        if exchange is None:
            return
        streaming = 'text/event-stream' in response.headers.get('content-type', '')
        if response.is_stream_consumed:
            if len(response.content) > MAX_BYTES:
                exchange.disable()
            elif streaming:
                exchange.feed(response.content)
                exchange.finish()
            else:
                try:
                    exchange.json(json.loads(response.content))
                except (ValueError, UnicodeError):
                    exchange.finish(stream=False, error=True)
        else:
            response.stream = ObservedStream(response.stream, exchange, stream=streaming)

    @passive_hook
    async def async_post_call_failure_hook(self, request_data, original_exception, user_api_key_dict, traceback_str=None):
        self._snapshot.set(None)

    def close(self):
        try:
            if self._recorder is not None:
                self._recorder.close()
        except Exception:
            self.failure()


recorder = ASRLogger()
