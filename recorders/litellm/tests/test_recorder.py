from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import subprocess

import httpx
import pytest

from asr_litellm.callback import ASRLogger
from asr_litellm.protocol import META, usage_for
from asr_litellm.recorder import Recorder

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).parent / 'fixtures'
HEADERS = {'user-agent': 'codex_exec/0.163.0', 'thread-id': 'synthetic-thread'}
BODY = {'model': 'synthetic-requested', 'tools': [], 'input': [{'role': 'user', 'content': 'Hello'}]}


def rows(recorder):
    return [json.loads(line) for path in sorted(recorder.directory.glob('*.jsonl')) for line in path.read_text().splitlines()]


def validate(recorder):
    for path in recorder.directory.glob('*.jsonl'):
        result = subprocess.run(['node', str(ROOT / 'tools/validator/bin/asr-validate.js'), str(path)], capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr


def respond(recorder, body=None, output=None, headers=None, rid='synthetic-response'):
    exchange = recorder.start('openai-responses', headers or HEADERS, body or BODY)
    exchange.json({'id': rid, 'model': 'synthetic-served', 'output': output or [], 'usage': {'input_tokens': 0, 'output_tokens': 0}})
    return exchange


@pytest.mark.parametrize('agent', ['claude-code', 'codex'])
def test_prototype_fixtures(tmp_path, agent):
    recorder = Recorder(tmp_path)
    fixture = [json.loads(line) for line in (FIXTURES / (agent + '.capture.jsonl')).read_text().splitlines()]
    for row in fixture:
        exchange = recorder.start(row['api'], row['requestHeaders'], json.loads(row['requestBody']), response_headers=row['responseHeaders'])
        if row['responseBody'].startswith(('event:', 'data:')):
            data = row['responseBody'].encode()
            for i in range(0, len(data), 7):
                exchange.feed(data[i:i + 7])
            exchange.finish()
        else:
            exchange.json(json.loads(row['responseBody']))
    recorder.close()
    records = rows(recorder)
    assert sum(r['type'] == 'session' for r in records) == 1
    assert sum(r['type'] == 'inference' for r in records) == len(fixture)
    calls = [r for r in records if r['type'] == 'tool_call']
    results = [r for r in records if r['type'] == 'tool_result']
    assert len(calls) == len(results) == 4
    assert all(r['status'] == 'unknown' for r in results)
    assert any(r.get('tools') for r in records)
    assert not any(r['type'] in ('approval', 'file_change', 'vcs') for r in records)
    validate(recorder)


def test_parallel_calls_repeat_history_and_changed_input(tmp_path):
    recorder = Recorder(tmp_path)
    calls = [{'type': 'function_call', 'id': f'item-{i}', 'call_id': f'call-{i}', 'name': 'shell', 'arguments': '{"cmd":"true"}'} for i in range(2)]
    respond(recorder, output=calls)
    results = [{'type': 'function_call_output', 'call_id': f'call-{i}', 'output': '', 'status': 'completed'} for i in (1, 0)]
    second = {**BODY, 'input': BODY['input'] + calls + results}
    respond(recorder, second, rid='synthetic-response-2')
    rewritten = deepcopy(second)
    rewritten['input'][1]['arguments'] = '{"cmd":"false"}'
    respond(recorder, rewritten, rid='synthetic-response-3')
    respond(recorder, rewritten, rid='synthetic-response-4')
    records = rows(recorder)
    assert len([r for r in records if r['type'] == 'tool_call']) == 2
    assert [r['callId'] for r in records if r['type'] == 'tool_result'] == ['call-1', 'call-0']
    assert len([r for r in records if 'rewrittenCallId' in r.get('_meta', {}).get(META, {})]) == 1
    validate(recorder)


def test_identical_messages_remain_distinct_and_rewrite_marks_gap(tmp_path):
    recorder = Recorder(tmp_path)
    respond(recorder)
    respond(recorder, {**BODY, 'input': BODY['input'] * 2}, rid='synthetic-response-2')
    assert len([r for r in rows(recorder) if r['type'] == 'message']) == 2
    respond(recorder, {**BODY, 'input': [{'role': 'user', 'content': 'A replacement'}]}, rid='synthetic-response-3')
    assert any(r['type'] == 'gap' for r in rows(recorder))
    validate(recorder)


def test_thread_identity_wins_over_root_and_parent_reference_encoding(tmp_path):
    recorder = Recorder(tmp_path)
    for thread in ('root', 'child:# %'):
        headers = {**HEADERS, 'thread-id': thread, 'session-id': 'root', 'x-codex-turn-metadata': json.dumps({'thread_id': thread, 'parent_thread_id': 'root:# %'} if thread != 'root' else {})}
        respond(recorder, headers=headers)
    sessions = [r for r in rows(recorder) if r['type'] == 'session']
    assert {s['sessionId'] for s in sessions} == {'root', 'child:# %'}
    assert next(s for s in sessions if s['sessionId'] != 'root')['parent']['session'] == 'codex:root%3A%23%20%25'
    validate(recorder)


def test_claude_metadata_and_subagent_grouping(tmp_path):
    recorder = Recorder(tmp_path)
    for agent in (None, 'synthetic-child'):
        headers = {'user-agent': 'claude-cli/2.1.305'}
        if agent:
            headers['x-claude-code-agent-id'] = agent
        body = {'model': 'synthetic', 'tools': [], 'messages': [], 'metadata': {'user_id': json.dumps({'session_id': 'synthetic-root'})}}
        exchange = recorder.start('anthropic-messages', headers, body)
        exchange.json({'id': f'response-{agent}', 'content': [], 'model': 'synthetic', 'usage': {'input_tokens': 1, 'cache_read_input_tokens': 2, 'cache_creation_input_tokens': 3, 'output_tokens': 0}})
    assert len(recorder.sessions) == 2
    assert all(r['usage']['inputTokens'] == 6 for r in rows(recorder) if r['type'] == 'inference')
    validate(recorder)


def test_previous_response_join_and_no_invented_identity(tmp_path):
    recorder = Recorder(tmp_path)
    respond(recorder)
    assert recorder.start('openai-responses', {}, BODY) is None
    exchange = recorder.start('openai-responses', {}, {**BODY, 'previous_response_id': 'synthetic-response', 'input': [{'role': 'user', 'content': 'Next'}]})
    exchange.json({'id': 'synthetic-next', 'output': []})
    assert len(recorder.sessions) == 1
    assert recorder.ungrouped == 1
    validate(recorder)


def test_tools_replace_at_position_and_namespaces(tmp_path):
    recorder = Recorder(tmp_path)
    body = {**BODY, 'tools': [{'type': 'function', 'name': 'first', 'parameters': {'type': 'object'}}]}
    respond(recorder, body)
    respond(recorder, {**BODY, 'input': [{'type': 'additional_tools', 'tools': [{'type': 'namespace', 'name': 'functions', 'tools': [{'type': 'function', 'name': 'exec', 'description': 'Run', 'parameters': {'type': 'object'}}]}]}]}, rid='synthetic-second')
    respond(recorder, rid='synthetic-third')
    definitions = [r['tools'] for r in rows(recorder) if 'tools' in r]
    assert [t[0]['name'] if t else None for t in definitions] == ['first', 'functions.exec', None]
    validate(recorder)


def test_credentials_and_opaque_state_never_persist(tmp_path):
    recorder = Recorder(tmp_path)
    secret = 'synthetic-' + 'credential-' * 6
    body = {**BODY, 'input': [{'role': 'user', 'content': f'Known credential: {secret}'}]}
    exchange = recorder.start('openai-responses', {**HEADERS, 'authorization': 'Bearer ' + secret, 'cookie': 'session=' + secret}, body)
    exchange.json({'id': 'synthetic-response', 'output': [{'type': 'reasoning', 'id': 'reasoning-1', 'encrypted_content': 'opaque-provider-state'}, {'type': 'message', 'role': 'assistant', 'content': secret}]})
    text = ''.join(p.read_text() for p in tmp_path.glob('*.jsonl'))
    assert secret not in text and 'opaque-provider-state' not in text
    assert 'authorization' not in text and 'cookie' not in text
    assert 'encrypted' in text and '[REDACTED]' in text
    assert any(r.get('truncated') for r in rows(recorder))
    losses = {loss for row in rows(recorder) for loss in row.get('missing', [])}
    assert 'redacted_content' in losses and 'redacted' not in losses
    assert any(r['type'] == 'gap' and r['reason'] == 'redacted' for r in rows(recorder))
    validate(recorder)


def test_stream_assembles_utf8_deltas_and_partial_calls_are_omitted(tmp_path):
    recorder = Recorder(tmp_path)
    exchange = recorder.start('anthropic-messages', {'user-agent': 'claude-cli/2.1.305', 'x-claude-code-session-id': 'synthetic-cl'}, {'model': 'synthetic', 'tools': [], 'messages': []})
    events = [{'type': 'message_start', 'message': {'id': 'native-response', 'model': 'served'}},
              {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}},
              {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': ' hé\n'}},
              {'type': 'content_block_start', 'index': 1, 'content_block': {'type': 'tool_use', 'id': 'unfinished', 'name': 'shell', 'input': {}}}]
    data = ''.join('data: ' + json.dumps(e, ensure_ascii=False) + '\r\n\r\n' for e in events).encode()
    for byte in data:
        exchange.feed(bytes([byte]))
    exchange.finish()
    records = rows(recorder)
    assert next(r for r in records if r['type'] == 'message')['content'][0]['text'] == ' hé\n'
    assert not any(r['type'] == 'tool_call' for r in records)
    assert any(r['type'] == 'gap' for r in records)
    validate(recorder)


def test_concurrent_completion_receipt_order_and_append_only(tmp_path):
    recorder = Recorder(tmp_path)
    one = recorder.start('openai-responses', HEADERS, BODY)
    path = next(tmp_path.glob('*.jsonl'))
    prefix = path.read_bytes()
    two = recorder.start('openai-responses', HEADERS, {**BODY, 'input': [{'role': 'user', 'content': 'intervening'}]})
    one.event({'type': 'response.created', 'response': {'id': 'response-one'}})
    one.event({'type': 'response.output_item.done', 'item': {'id': 'item-one', 'type': 'message', 'role': 'assistant', 'content': 'first complete'}})
    two.json({'id': 'response-two', 'output': [{'type': 'message', 'role': 'assistant', 'content': 'second complete'}]})
    one.event({'type': 'response.completed', 'response': {'id': 'response-one'}})
    one.finish()
    assert path.read_bytes().startswith(prefix)
    records = rows(recorder)
    relevant = [r for r in records if r['type'] == 'inference' or r.get('role') == 'assistant']
    assert [r['type'] for r in relevant] == ['message', 'message', 'inference', 'inference']
    validate(recorder)


@pytest.mark.parametrize('stream', [False, True])
def test_real_litellm_headers_callback_preserves_http_bytes(tmp_path, stream):
    async def run():
        logger = ASRLogger(tmp_path)
        response_body = {'id': 'synthetic-response', 'model': 'served', 'output': [{'type': 'message', 'role': 'assistant', 'content': 'answer'}]}
        payload = ('data: ' + json.dumps({'type': 'response.completed', 'response': response_body}) + '\n\n').encode() if stream else json.dumps(response_body).encode()

        class Source(httpx.AsyncByteStream):
            async def __aiter__(self):
                for offset in range(0, len(payload), 3):
                    yield payload[offset:offset + 3]

        request = httpx.Request('POST', 'http://example.invalid/v1/responses', headers=HEADERS, json=BODY)
        response = httpx.Response(200, request=request, headers={'content-type': 'text/event-stream' if stream else 'application/json'}, stream=Source())
        await logger.async_pre_call_hook(None, None, BODY, 'pass_through_endpoint')
        assert await logger.async_post_call_response_headers_hook({}, None, response, HEADERS) is None
        assert await response.aread() == payload
        await response.aclose()
        logger.close()
        validate(logger.recorder)
        assert len([r for r in rows(logger.recorder) if r['type'] == 'inference']) == 1
    asyncio.run(run())


def test_inclusive_usage_zero_and_unknown():
    assert usage_for('anthropic-messages', {'input_tokens': 0, 'output_tokens': 0}) == {'inputTokens': 0, 'outputTokens': 0}
    assert usage_for('openai-responses', {'input_tokens': 4, 'input_tokens_details': {'cached_tokens': 3}}) == {'inputTokens': 4, 'cacheReadTokens': 3}
    assert usage_for('openai-responses', None) is None


def test_invalid_sse_and_large_counts_declare_loss(tmp_path):
    recorder = Recorder(tmp_path)
    exchange = recorder.start('openai-responses', HEADERS, BODY)
    exchange.feed(b'data: not json\n\ndata: {')
    exchange.event({'type': 'response.completed', 'response': {'id': 'synthetic-response', 'usage': {'input_tokens': 2**55, 'output_tokens': 0}}})
    exchange.finish()
    records = rows(recorder)
    inference = next(r for r in records if r['type'] == 'inference')
    assert inference['usage'] == {'outputTokens': 0}
    assert inference['_meta'][META]['providerUsage']['input_tokens'] == str(2**55)
    assert any('usage' in r.get('missing', []) for r in records)
    validate(recorder)


def test_effective_arguments_learned_from_client_echo(tmp_path):
    recorder = Recorder(tmp_path)
    call = {'type': 'function_call', 'id': 'item', 'call_id': 'call', 'name': 'edit', 'arguments': '{"text":"x"}'}
    respond(recorder, output=[call])
    effective = {**call, 'arguments': '{"text":"x","replace_all":false}'}
    respond(recorder, {**BODY, 'input': BODY['input'] + [effective, {'type': 'function_call_output', 'call_id': 'call', 'output': ''}]}, rid='response-two')
    records = rows(recorder)
    assert next(r for r in records if r['type'] == 'tool_call')['input'] == {'text': 'x'}
    assert next(r for r in records if r['type'] == 'tool_result')['input'] == {'text': 'x', 'replace_all': False}
    validate(recorder)


def test_reused_call_ids_are_ambiguous_and_do_not_drop_model_work(tmp_path):
    recorder = Recorder(tmp_path)
    call = {'type': 'function_call', 'id': 'item-one', 'call_id': 'same-call', 'name': 'shell', 'arguments': '{}'}
    respond(recorder, output=[call])
    respond(recorder, {**BODY, 'input': BODY['input'] + [call]}, output=[{**call, 'id': 'item-two'}], rid='response-two')
    calls = [r for r in rows(recorder) if r['type'] == 'tool_call']
    assert len(calls) == 2
    assert len({r['id'] for r in calls}) == 2
    validate(recorder)


def test_claude_partial_json_parallel_tools_and_failed_result(tmp_path):
    recorder = Recorder(tmp_path)
    headers = {'user-agent': 'claude-cli/2.1.305', 'x-claude-code-session-id': 'synthetic-cl'}
    body = {'model': 'synthetic', 'tools': [], 'messages': []}
    exchange = recorder.start('anthropic-messages', headers, body)
    exchange.event({'type': 'message_start', 'message': {'id': 'native-response', 'model': 'served'}})
    for index in (0, 1):
        exchange.event({'type': 'content_block_start', 'index': index, 'content_block': {'type': 'tool_use', 'id': f'call-{index}', 'name': 'shell', 'input': {}}})
        for text in ('{"cmd":', '"true"}'):
            exchange.event({'type': 'content_block_delta', 'index': index, 'delta': {'type': 'input_json_delta', 'partial_json': text}})
    for index in (1, 0):
        exchange.event({'type': 'content_block_stop', 'index': index})
    exchange.event({'type': 'message_stop'})
    exchange.finish()
    assert [r['callId'] for r in rows(recorder) if r['type'] == 'tool_call'] == ['call-1', 'call-0']
    second = recorder.start('anthropic-messages', headers, {**body, 'messages': [{'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call-1', 'is_error': True, 'content': 'refused'}]}]})
    second.json({'id': 'native-two', 'content': []})
    assert next(r for r in rows(recorder) if r['type'] == 'tool_result')['status'] == 'failed'
    assert not any(r['type'] == 'approval' for r in rows(recorder))
    validate(recorder)


def test_terminal_event_followed_by_client_close_is_complete(tmp_path):
    recorder = Recorder(tmp_path)
    exchange = recorder.start('openai-responses', HEADERS, BODY)
    exchange.event({'type': 'response.completed', 'response': {'id': 'native-response', 'model': 'served', 'output': []}})
    exchange.finish(error=True)
    assert not any(r['type'] == 'gap' for r in rows(recorder))
    assert 'error' not in next(r for r in rows(recorder) if r['type'] == 'inference')
    validate(recorder)


def test_input_encrypted_reasoning_keeps_visibility(tmp_path):
    recorder = Recorder(tmp_path)
    respond(recorder, {**BODY, 'input': [{'type': 'reasoning', 'id': 'reasoning', 'encrypted_content': 'opaque-native-state'}]})
    assert next(r for r in rows(recorder) if r['type'] == 'message')['content'] == [{'type': 'reasoning', 'visibility': 'encrypted'}]
    assert 'opaque-native-state' not in ''.join(p.read_text() for p in tmp_path.glob('*.jsonl'))
    validate(recorder)


def test_adjacent_anthropic_stream_parts_do_not_duplicate_echoed_history(tmp_path):
    recorder = Recorder(tmp_path)
    headers = {'user-agent': 'claude-cli/2.1.305', 'x-claude-code-session-id': 'synthetic-cl'}
    body = {'model': 'synthetic', 'tools': [], 'messages': []}
    exchange = recorder.start('anthropic-messages', headers, body)
    exchange.event({'type': 'message_start', 'message': {'id': 'native-response', 'model': 'served'}})
    content = [{'type': 'thinking', 'thinking': 'think'}, {'type': 'text', 'text': 'answer'}]
    for index, block in enumerate(content):
        exchange.event({'type': 'content_block_start', 'index': index, 'content_block': block})
        exchange.event({'type': 'content_block_stop', 'index': index})
    exchange.event({'type': 'message_stop'})
    exchange.finish()
    second = recorder.start('anthropic-messages', headers, {**body, 'messages': [{'role': 'assistant', 'content': content}]})
    second.json({'id': 'second-response', 'content': []})
    assert len([r for r in rows(recorder) if r['type'] == 'message']) == 2
    assert not any(r['type'] == 'gap' for r in rows(recorder))
    validate(recorder)


def test_compaction_keeps_prior_work_and_marks_loss_at_its_position(tmp_path):
    recorder = Recorder(tmp_path)
    respond(recorder)
    respond(recorder, {**BODY, 'input': [{'type': 'compaction', 'encrypted_content': 'opaque-compaction-state'}]}, rid='response-two')
    records = rows(recorder)
    compact = next(i for i, r in enumerate(records) if r.get('origin') == 'compaction')
    assert any(r['type'] == 'gap' and r['reason'] == 'not_retained' for r in records[compact + 1:])
    assert any(r.get('role') == 'user' for r in records[:compact])
    assert all('copiedFrom' not in r for r in records)
    validate(recorder)


def test_error_text_is_not_an_approval_or_execution_status(tmp_path):
    recorder = Recorder(tmp_path)
    respond(recorder, {**BODY, 'input': [{'type': 'function_call_output', 'call_id': 'unseen', 'output': 'Permission denied. Exit code 7.'}]})
    result = next(r for r in rows(recorder) if r['type'] == 'tool_result')
    assert result['status'] == 'unknown' and 'exec' not in result
    assert not any(r['type'] == 'approval' for r in rows(recorder))
    validate(recorder)


def test_http_error_keeps_one_inference_without_filling_missing_facts(tmp_path):
    recorder = Recorder(tmp_path)
    exchange = recorder.start('openai-responses', HEADERS, BODY, status=429)
    exchange.json({'error': {'message': 'Synthetic rate limit', 'code': 'rate_limit'}})
    inference = next(r for r in rows(recorder) if r['type'] == 'inference')
    assert inference['error']['code'] == 'rate_limit'
    assert inference['model'] == {'requested': BODY['model']}
    assert 'cost' not in inference and 'usage' not in inference
    validate(recorder)


def test_existing_file_is_never_rewritten_and_output_is_private(tmp_path):
    recorder = Recorder(tmp_path)
    respond(recorder)
    path = next(tmp_path.glob('*.jsonl'))
    original = path.read_bytes()
    recorder.close()
    restarted = Recorder(tmp_path)
    respond(restarted)
    restarted.close()
    assert len(list(tmp_path.glob("*.jsonl"))) == 2
    assert any("capture_restart" in row.get("missing", []) for row in rows(restarted))
    assert any(row["type"] == "gap" and row["reason"] == "not_recorded" for row in rows(restarted))
    validate(restarted)
    assert path.read_bytes() == original
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('case', ['missing-output', 'bad-json', 'null-body', 'bad-item', 'bad-messages', 'null-settings', 'writer-feed', 'writer-finish', 'restart'])
@pytest.mark.parametrize('stream', [False, True])
def test_capture_faults_never_change_client_bytes(case, stream, tmp_path, monkeypatch):
    async def run():
        from agent_session_record import Writer
        monkeypatch.delenv('ASR_OUTPUT_DIR', raising=False)
        logger = ASRLogger(None if case == 'missing-output' else tmp_path)
        body = {**BODY, 'reasoning': None, 'output_config': None}
        api = 'responses'
        if case == 'bad-item':
            body['input'] = [None]
        if case == 'bad-messages':
            body = {'model': 'synthetic', 'messages': [None]}
            api = 'messages'
        if case == 'restart':
            old = Recorder(tmp_path)
            respond(old)
            old.close()
        headers = HEADERS if api == 'responses' else {'user-agent': 'claude-cli/2.1.305', 'x-claude-code-session-id': 'synthetic-cl'}
        raw = b'not-json' if case == 'bad-json' else b'null' if case == 'null-body' else json.dumps(body).encode()
        content = {'id': 'synthetic-response-next', 'model': 'served', 'output': [], 'content': []}
        events = [{'type': 'response.created', 'response': content}, {'type': 'response.completed', 'response': content}]
        payload = ''.join('data: ' + json.dumps(event) + '\n\n' for event in events).encode() if stream else json.dumps(content).encode()
        chunks = [payload[i:i+7] for i in range(0, len(payload), 7)]
        class Source(httpx.AsyncByteStream):
            async def __aiter__(self):
                for chunk in chunks:
                    yield chunk
        request = httpx.Request('POST', 'http://example.invalid/v1/' + api, headers=headers, content=raw)
        response = httpx.Response(200, request=request, headers={'content-type': 'text/event-stream' if stream else 'application/json'}, stream=Source())
        assert await logger.async_post_call_response_headers_hook({}, None, response, headers) is None
        if case in ('writer-feed', 'writer-finish'):
            original = Writer.append
            def broken(writer, record):
                if case == 'writer-feed' or record['type'] == 'inference':
                    raise OSError('synthetic write failure')
                return original(writer, record)
            monkeypatch.setattr(Writer, 'append', broken)
        assert [chunk async for chunk in response.aiter_raw()] == chunks
        await response.aclose()
        assert await logger.async_pre_call_hook(None, None, body, 'pass_through_endpoint') is None
        assert await logger.async_post_call_failure_hook({}, RuntimeError('synthetic'), None) is None
        logger.close()
        if case == 'null-settings':
            inference = next(row for row in rows(logger.recorder) if row['type'] == 'inference')
            assert inference['settings'] == {}
        if logger._recorder is not None:
            validate(logger.recorder)
    asyncio.run(run())


@pytest.mark.parametrize('method', ['feed', 'finish'])
def test_tee_defends_against_exchange_method_raising(method):
    from asr_litellm.callback import ObservedStream
    async def run():
        class Source(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'original-one'
                yield b'original-two'
        class Broken:
            def feed(self, chunk):
                if method == 'feed':
                    raise RuntimeError('synthetic')
            def finish(self, **kwargs):
                raise ValueError('synthetic')
        tee = ObservedStream(Source(), Broken())
        assert [chunk async for chunk in tee] == [b'original-one', b'original-two']
        await tee.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('status', [200, 429])
def test_error_without_provider_message_uses_only_status(tmp_path, status):
    rec = Recorder(tmp_path)
    exchange = rec.start('openai-responses', HEADERS, BODY, status=status)
    exchange.finish(error=True)
    inference = next(row for row in rows(rec) if row['type'] == 'inference')
    assert inference['error'] == ({'code': status} if status >= 400 else {})
    validate(rec)


def test_headers_and_request_settings_are_allowlisted(tmp_path):
    rec = Recorder(tmp_path)
    exchange = rec.start('openai-responses', {**HEADERS, 'x-forwarded-for': 'synthetic-client', 'openai-project': 'synthetic-project'},
                         {**BODY, 'user': 'synthetic-user', 'safety_identifier': 'synthetic-person', 'max_output_tokens': 8},
                         response_headers={'anthropic-organization-id': 'synthetic-organization', 'request-id': 'synthetic-request'})
    exchange.json({'output': []})
    inference = next(row for row in rows(rec) if row['type'] == 'inference')
    meta = inference['_meta'][META]
    assert meta['requestSettings'] == {'max_output_tokens': 8}
    assert meta['responseHeaders'] == {'request-id': 'synthetic-request'}
    assert 'x-forwarded-for' not in meta['requestHeaders']
    assert 'synthetic-project' not in json.dumps(meta)
    validate(rec)


def test_claude_thinking_is_a_summary(tmp_path):
    rec = Recorder(tmp_path)
    exchange = rec.start('anthropic-messages', {'user-agent': 'claude-cli/2.1.305', 'x-claude-code-session-id': 'synthetic-cl'}, {'model': 'claude-4', 'messages': []})
    exchange.json({'model': 'claude-4', 'content': [{'type': 'thinking', 'thinking': 'visible summary', 'signature': 'opaque-state'}]})
    part = next(row for row in rows(rec) if row['type'] == 'message')['content'][0]
    assert part == {'type': 'reasoning', 'visibility': 'summary', 'summary': ['visible summary']}
    validate(rec)


def test_gateway_memory_limits_emit_gaps_and_restart(tmp_path, monkeypatch):
    import asr_litellm.recorder as module
    monkeypatch.setattr(module, 'MAX_SESSIONS', 2)
    monkeypatch.setattr(module, 'MAX_RESPONSES', 2)
    monkeypatch.setattr(module, 'MAX_HISTORY', 2)
    rec = Recorder(tmp_path)
    for index in range(6):
        exchange = respond(rec, {**BODY, 'previous_response_id': f'synthetic-{index-1}'}, headers={**HEADERS, 'thread-id': 'synthetic-' + str(index % 3)}, rid=f'synthetic-{index}')
        assert len(rec.sessions) <= 2 and len(rec.response_sessions) <= 2
        assert len(exchange.session.expected) <= 2
    assert any(row['type'] == 'gap' for row in rows(rec))
    validate(rec)


def test_oversized_sse_frame_disables_capture_without_retaining_bytes(tmp_path):
    rec = Recorder(tmp_path)
    exchange = rec.start('openai-responses', HEADERS, BODY)
    exchange.feed(b'x' * (2 * 1024 * 1024 + 1))
    assert exchange.disabled and not exchange.sse.buffer
    validate(rec)


def test_nonstream_buffer_limit_keeps_forwarding_exact_chunks(tmp_path, monkeypatch):
    import asr_litellm.callback as module
    async def run():
        monkeypatch.setattr(module, 'MAX_BYTES', 16)
        logger = ASRLogger(tmp_path)
        # An existing request snapshot can fit while the response exceeds its cap.
        request = httpx.Request('POST', 'http://example.invalid/v1/responses', headers=HEADERS, content=b'{}')
        chunks = [b'x' * 10, b'y' * 10, b'z' * 10]
        class Source(httpx.AsyncByteStream):
            async def __aiter__(self):
                for chunk in chunks:
                    yield chunk
        response = httpx.Response(200, request=request, stream=Source(), headers={'content-type': 'application/json'})
        await logger.async_post_call_response_headers_hook({}, None, response, HEADERS)
        tee = response.stream
        assert [chunk async for chunk in response.aiter_raw()] == chunks
        assert tee.disabled and not tee.buffer
        logger.close()
        assert any(row['type'] == 'gap' for row in rows(logger.recorder))
        validate(logger.recorder)
    asyncio.run(run())


def test_deeply_malformed_json_response_cannot_break_forwarding(tmp_path):
    async def run():
        logger = ASRLogger(tmp_path)
        payload = b'[' * 2000 + b']' * 2000
        class Source(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield payload
        request = httpx.Request('POST', 'http://example.invalid/v1/responses', headers=HEADERS, json=BODY)
        response = httpx.Response(200, request=request, stream=Source())
        await logger.async_post_call_response_headers_hook({}, None, response, HEADERS)
        assert await response.aread() == payload
        logger.close()
        validate(logger.recorder)
    asyncio.run(run())


def test_open_response_blocks_have_an_aggregate_memory_cap(tmp_path, monkeypatch):
    import asr_litellm.recorder as module
    monkeypatch.setattr(module, 'MAX_BYTES', 1024)
    rec = Recorder(tmp_path)
    exchange = rec.start('anthropic-messages', {'user-agent': 'claude-cli/2.1.305', 'x-claude-code-session-id': 'synthetic-cl'}, {'messages': []})
    for index in range(3):
        exchange.event({'type': 'content_block_start', 'index': index, 'content_block': {'type': 'text', 'text': 'x' * 500}})
    assert exchange.disabled and not exchange.blocks
    validate(rec)


def test_oversized_request_with_known_session_leaves_gap(tmp_path, monkeypatch):
    import asr_litellm.callback as module
    async def run():
        monkeypatch.setattr(module, 'MAX_BYTES', 16)
        logger = ASRLogger(tmp_path)
        payload = b'original response'
        request = httpx.Request('POST', 'http://example.invalid/v1/responses', headers=HEADERS, content=b'x' * 100)
        response = httpx.Response(200, request=request, content=payload)
        await logger.async_post_call_response_headers_hook({}, None, response, HEADERS)
        assert await response.aread() == payload
        assert any(row['type'] == 'gap' for row in rows(logger.recorder))
        logger.close()
        validate(logger.recorder)
    asyncio.run(run())


def test_empty_thinking_and_provider_summary_never_claim_full_reasoning():
    from asr_litellm.protocol import parts, response_atoms
    assert parts([{'type': 'thinking', 'thinking': '', 'signature': 'opaque'}]) == [{'type': 'reasoning', 'visibility': 'omitted'}]
    assert response_atoms([{'type': 'reasoning', 'summary': [{'text': ''}]}])[0]['content'] == [{'type': 'reasoning', 'visibility': 'omitted'}]
    assert response_atoms([{'type': 'reasoning', 'summary': [{'text': 'summary'}], 'encrypted_content': True}])[0]['content'] == [{'type': 'reasoning', 'visibility': 'summary', 'summary': ['summary']}]
