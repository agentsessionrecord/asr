from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from http.server import HTTPServer
import json
from pathlib import Path
import subprocess
from threading import Thread
from urllib.request import Request, urlopen

import grpc
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from envoy.service.ext_proc.v3 import external_processor_pb2 as pb
from envoy.service.ext_proc.v3 import external_processor_pb2_grpc as rpc
from google.protobuf.json_format import ParseDict

from asr_gateways import GatewayRecorder
from asr_gateways.cli import handler
from asr_gateways.envoy import Processor
from asr_portkey import capture as portkey
from asr_helicone import capture as helicone
from asr_cloudflare import capture as cloudflare

ROOT = Path(__file__).resolve().parents[3]
HEADERS = {'user-agent': 'claude-cli/2.1.305', 'x-claude-code-session-id': 'synthetic-session'}
REQUEST = {'model': 'synthetic-alias', 'max_tokens': 32, 'messages': [{'role': 'user', 'content': 'Reply with a number.'}]}
RESPONSE = {'id': 'synthetic-response', 'type': 'message', 'model': 'synthetic-served', 'content': [{'type': 'text', 'text': '1'}], 'stop_reason': 'end_turn', 'usage': {'input_tokens': 1, 'output_tokens': 0, 'cache_read_input_tokens': 2}}


def test_envoy_bounds_bodies_and_acknowledges_after_capture_failure(recorder, monkeypatch):
    import asr_gateways.envoy as module
    monkeypatch.setattr(module, 'MAX_BODY', 8)
    frames = [pb.ProcessingRequest(request_body=pb.HttpBody(body=b'12345678')),
              pb.ProcessingRequest(request_body=pb.HttpBody(body=b'9', end_of_stream=True)),
              pb.ProcessingRequest(response_body=pb.HttpBody(body=b'{}', end_of_stream=True))]
    assert len(list(Processor(recorder).Process(iter(frames), None))) == len(frames)
    assert recorder.skipped == 1 and not list(recorder.recorder.directory.glob('*.jsonl'))
    def broken(*args, **kwargs):
        raise OSError('synthetic-storage-failure')
    monkeypatch.setattr(recorder, 'capture', broken)
    frames = [pb.ProcessingRequest(request_body=pb.HttpBody(body=b'{}', end_of_stream=True)),
              pb.ProcessingRequest(response_body=pb.HttpBody(body=b'{}', end_of_stream=True))]
    assert len(list(Processor(recorder).Process(iter(frames), None))) == len(frames)
    assert recorder.skipped == 2
    header = pb.ProcessingRequest()
    header.request_headers.headers.headers.add(key='x-synthetic', raw_value=b'\xff')
    frames = [header, pb.ProcessingRequest(request_body=pb.HttpBody(body=b'{}')),
              pb.ProcessingRequest(response_body=pb.HttpBody(body=b'{}', end_of_stream=True))]
    assert len(list(Processor(recorder).Process(iter(frames), None))) == len(frames)
    assert recorder.skipped == 3


@pytest.fixture
def recorder(tmp_path):
    value = GatewayRecorder(tmp_path)
    yield value
    value.close()
    for path in tmp_path.rglob('*.jsonl'):
        result = subprocess.run(['node', str(ROOT / 'tools/validator/bin/asr-validate.js'), str(path)], capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr


def read(recorder):
    return [json.loads(line) for line in next(recorder.recorder.directory.glob('*.jsonl')).read_text().splitlines()]


def context():
    return {'requestType': 'messages', 'provider': 'anthropic', 'metadata': {},
            'request': {'json': deepcopy(REQUEST), 'headers': HEADERS, 'isStreamingRequest': False, 'isTransformed': False},
            'response': {'json': deepcopy(RESPONSE), 'statusCode': 200, 'isTransformed': False}}


def test_native_portkey_fixture_and_accounting(recorder):
    path = ROOT / 'recorders/portkey/tests/fixtures/after-request.jsonl'
    for line in path.read_text().splitlines():
        event = json.loads(line)
        assert portkey(recorder, event['payload'])
    data = read(recorder)
    inference = next(r for r in data if r['type'] == 'inference')
    assert inference['model'] == {'requested': 'synthetic-alias', 'id': 'synthetic-served'}
    assert inference['usage'] == {'inputTokens': 3, 'outputTokens': 0, 'cacheReadTokens': 2}
    assert not any(r['type'] == 'approval' for r in data)


def test_portkey_rejects_translation_streaming_and_unknown_identity(recorder):
    for flag in ['isStreamingRequest', 'isTransformed']:
        event = context()
        event['request'][flag] = True
        assert portkey(recorder, event) is False
    event = context()
    event['requestType'] = 'chatComplete'
    assert portkey(recorder, event) is False
    event = context()
    event['request']['headers'] = {'x-portkey-trace-id': 'a-trace-is-not-a-session'}
    assert portkey(recorder, event) is False
    assert not list(recorder.recorder.directory.glob('*.jsonl'))


def test_helicone_real_http_boundary_and_secrets(recorder):
    server = HTTPServer(('127.0.0.1', 0), handler(recorder, helicone, ('/anthropic/v1/log',)))
    thread = Thread(target=server.handle_request)
    thread.start()
    secret = 'synthetic-' + 'private-key-value'
    event = json.loads((ROOT / 'recorders/helicone/tests/fixtures/manual.jsonl').read_text())
    body = deepcopy(event['payload'])
    body['providerRequest']['json']['messages'][0]['content'] = secret
    request = Request(f'http://127.0.0.1:{server.server_port}/anthropic/v1/log', data=json.dumps(body).encode(), headers={**HEADERS, 'authorization': 'Bearer ' + secret, 'content-type': 'application/json'})
    try:
        with urlopen(request, timeout=5) as response:
            assert response.status == 200
    finally:
        thread.join(5)
        server.server_close()
    assert secret not in next(recorder.recorder.directory.glob('*.jsonl')).read_text()
    assert any(r.get('truncated') for r in read(recorder))


def test_cloudflare_encrypted_logpush_and_untrusted_uri(recorder):
    event = json.loads((ROOT / 'recorders/cloudflare/tests/fixtures/logpush.jsonl').read_text())
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    aes, iv = AESGCM.generate_key(bit_length=256), b'123456789012'
    def encrypted(value):
        text = json.dumps(value) if not isinstance(value, str) else value
        encode = lambda value: base64.b64encode(value).decode()
        return {'key': encode(private.public_key().encrypt(aes, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))), 'iv': encode(iv), 'data': encode(AESGCM(aes).encrypt(iv, text.encode(), None))}
    for field in ('Metadata', 'RequestBody', 'ResponseBody'):
        event[field] = encrypted(event[field])
    assert cloudflare(recorder, event, private_key=private)
    damaged = deepcopy(event)
    damaged['ResponseBody']['data'] = 'invalid'
    with pytest.raises(ValueError):
        cloudflare(recorder, damaged, private_key=private)
    assert next(r for r in read(recorder) if r['type'] == 'inference')['usage']['inputTokens'] == 3


def test_envoy_native_grpc_receipts_preserve_body(recorder):
    messages = [ParseDict(event, pb.ProcessingRequest()) for event in json.loads((ROOT / 'recorders/envoy/tests/fixtures/ext-proc.json').read_text())]
    server = grpc.server(ThreadPoolExecutor(max_workers=1))
    rpc.add_ExternalProcessorServicer_to_server(Processor(recorder), server)
    port = server.add_insecure_port('127.0.0.1:0')
    server.start()
    try:
        with grpc.insecure_channel(f'127.0.0.1:{port}') as channel:
            results = list(rpc.ExternalProcessorStub(channel).Process(iter(messages), timeout=5))
        assert [v.WhichOneof('response') for v in results] == ['request_headers', 'request_body', 'response_headers', 'response_body']
        assert all(not value.HasField('response') for value in [r.request_body for r in results if r.WhichOneof('response') == 'request_body'])
    finally:
        server.stop(0).wait()
    assert recorder.accepted == 1
    assert next(r for r in read(recorder) if r['type'] == 'inference')['model']['id'] == 'synthetic-served'


def test_sse_uses_shared_fold_and_missing_terminal(recorder):
    stream = '\n\n'.join('data: ' + json.dumps(v) for v in [
        {'type': 'message_start', 'message': {'id': 'stream-response', 'model': 'served', 'usage': {'input_tokens': 1}}},
        {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}},
        {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': 'ab'}},
        {'type': 'content_block_stop', 'index': 0},
    ]) + '\n\n'
    assert recorder.capture('anthropic-messages', HEADERS, REQUEST, stream)
    data = read(recorder)
    assert any(r['type'] == 'gap' for r in data)
    assert next(r for r in data if r['type'] == 'message' and r.get('role') == 'assistant')['content'] == [{'type': 'text', 'text': 'ab'}]


def test_gateway_reuses_session_and_reports_status_only_error(recorder):
    assert recorder.capture('anthropic-messages', HEADERS, REQUEST, RESPONSE)
    assert recorder.capture('anthropic-messages', HEADERS, REQUEST, {}, status=503)
    inferences = [r for r in read(recorder) if r['type'] == 'inference']
    assert len(inferences) == 2
    assert inferences[-1]['error'] == {'code': 503}
    assert recorder.recorder.failures == 0


def test_gateway_restart_and_rotation_keep_gateway_header(tmp_path, monkeypatch):
    import asr_litellm.recorder as core

    original = None
    for _ in range(2):
        value = GatewayRecorder(tmp_path, gateway='cloudflare', historical=True)
        try:
            assert value.capture('anthropic-messages', HEADERS, REQUEST, RESPONSE)
            if original is None:
                original = next(tmp_path.glob('*.jsonl'))
                before = original.read_bytes()
            else:
                monkeypatch.setattr(core, 'MAX_RECORDS', 1)
                assert value.capture('anthropic-messages', HEADERS, REQUEST, RESPONSE)
            assert value.recorder.failures == 0
        finally:
            value.close()
    assert original.read_bytes() == before
    captures = sorted(tmp_path.glob('*.jsonl'))
    assert len(captures) == 3
    for path in captures:
        records = [json.loads(line) for line in path.read_text().splitlines()]
        assert records[0]['sessionId'] == HEADERS['x-claude-code-session-id']
        assert records[0]['producer']['name'] == 'asr-cloudflare'
        assert records[0]['producer']['method'] == 'converter'
        assert all('ts' not in r and 'durationMs' not in r for r in records)
        if path != original:
            assert 'capture_restart' in records[0]['missing']
            assert next(r for r in records[1:] if r['type'] == 'gap')['reason'] == 'not_recorded'
        result = subprocess.run(['node', str(ROOT / 'tools/validator/bin/asr-validate.js'), str(path)], capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr


def test_existing_repository_examples_and_samples():
    paths = sorted((ROOT / 'samples').glob('*/asr/*.jsonl')) + sorted((ROOT / 'examples').glob('*.jsonl'))
    assert paths
    # Exercise the same structural contract for the established corpus without copying private data.
    for path in paths:
        result = subprocess.run(['node', str(ROOT / 'tools/validator/bin/asr-validate.js'), str(path)], capture_output=True, text=True)
        assert result.returncode == 0, f'{path.name}: {result.stdout}{result.stderr}'


def test_offline_logs_do_not_acquire_playback_times(tmp_path):
    recorder = GatewayRecorder(tmp_path, gateway='cloudflare', historical=True)
    event = json.loads((ROOT / 'recorders/cloudflare/tests/fixtures/logpush.jsonl').read_text())
    try:
        assert cloudflare(recorder, event)
        data = read(recorder)
        assert data[0]['producer'] == {'name': 'asr-cloudflare', 'version': '0.1.0', 'method': 'converter', 'source': 'cloudflare:anthropic-messages'}
        assert 'timestamps' in data[0]['missing']
        assert all('ts' not in r and 'durationMs' not in r for r in data)
        inference = next(r for r in data if r['type'] == 'inference')
        assert 'upstreamStatus' not in inference['_meta']['org.agentsessionrecord.litellm']
        assert 'firstObservedAt' not in inference['_meta']['org.agentsessionrecord.litellm']
    finally:
        recorder.close()
    result = subprocess.run(['node', str(ROOT / 'tools/validator/bin/asr-validate.js'), str(next(tmp_path.glob('*.jsonl')))], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_gateway_thinking_is_summarized_or_omitted_without_repository_guessing(recorder):
    response = deepcopy(RESPONSE)
    response['content'] = [{'type': 'thinking', 'thinking': '', 'signature': 'opaque'},
                           {'type': 'thinking', 'thinking': 'Visible summary', 'signature': 'opaque'}]
    assert recorder.capture('anthropic-messages', HEADERS, REQUEST, response)
    rows = read(recorder)
    assert 'cwd' not in rows[0] and 'repos' not in rows[0]
    reply = next(r for r in rows if r['type'] == 'message' and r['role'] == 'assistant')
    assert reply['content'] == [{'type': 'reasoning', 'visibility': 'omitted'},
                                {'type': 'reasoning', 'visibility': 'summary', 'summary': ['Visible summary']}]
    assert 'opaque' not in json.dumps(rows)
