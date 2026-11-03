from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from asr_acp import Recorder
from asr_acp.recorder import META

ROOT = Path(__file__).resolve().parents[3]
T = '2026-10-31T12:00:00Z'


def test_native_session_reference_uses_shared_encoding(tmp_path):
    recorder = Recorder(tmp_path, 'com.example.agent', clock=lambda: T)
    try:
        assert recorder.reference('run/é: #%\x85') == 'com.example.agent:run/é%3A%20%23%25%C2%85'
    finally:
        recorder.close()


@pytest.fixture
def capture(tmp_path):
    recorders = []
    def make(**kwargs):
        recorder = Recorder(tmp_path / str(len(recorders)), 'com.example.agent', clock=lambda: T, **kwargs)
        recorders.append(recorder)
        return recorder
    yield make
    for recorder in recorders:
        recorder.close()
    for path in tmp_path.rglob('*.jsonl'):
        result = subprocess.run(['node', str(ROOT / 'tools/validator/bin/asr-validate.js'), str(path)], capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr


def records(recorder, sid='s'):
    return [json.loads(line) for line in recorder.sessions[sid].path.read_text().splitlines()]


def update(recorder, value, sid='s'):
    recorder.observe('agent', {'method': 'session/update', 'params': {'sessionId': sid, 'update': value}})


def rpc(recorder, method, params, result, request_side='client', ident=1):
    recorder.observe(request_side, {'id': ident, 'method': method, 'params': params})
    recorder.observe('agent' if request_side == 'client' else 'client', {'id': ident, **result})


def tool(recorder, cid='c', **kwargs):
    update(recorder, {'sessionUpdate': 'tool_call_update', 'toolCallId': cid, **kwargs})


def test_fixture_and_completion_order(capture):
    recorder = capture()
    for line in Path(__file__).with_name('fixtures').joinpath('v2.traffic.jsonl').read_text().splitlines():
        event = json.loads(line)
        recorder.observe(event['direction'], event['message'])
    data = records(recorder)
    assert [r['type'] for r in data] == ['session', 'session_info', 'tool_call', 'approval', 'tool_result', 'message', 'session_info']
    assert data[2]['callId'] == 'c'
    assert data[3]['decision'] == 'denied' and data[3]['scope'] == 'once'
    assert 'by' not in data[3]
    assert data[4]['status'] == 'failed'
    assert data[5]['content'] == [{'type': 'text', 'text': 'ab\n'}]
    assert data[5]['id'] == 'm'
    assert 'endedAt' not in data[-1]


@pytest.mark.parametrize('source', ['message', 'chunk', 'thought', 'prompt', 'tool', 'notice', 'compaction'])
def test_unknown_content_uses_vendor_part_names(capture, source):
    recorder = capture()
    native = {'type': '_document', 'title': 'Synthetic document', 'enabled': False}
    parts = [{'type': 'text', 'text': 'before'}, native, {'type': 'text', 'text': 'after'}]
    if source == 'prompt':
        rpc(recorder, 'session/prompt', {'sessionId': 's', 'prompt': parts},
            {'result': {'messageId': 'p'}})
    elif source == 'tool':
        tool(recorder, name='read', status='completed',
             content=[{'type': 'content', 'content': part} for part in parts])
    elif source == 'notice':
        update(recorder, {'sessionUpdate': 'notice', 'content': parts})
    elif source == 'compaction':
        update(recorder, {'sessionUpdate': 'compaction_update', 'compactionId': 'co',
                          'status': 'completed', 'summary': parts})
    else:
        kind = 'agent_thought' if source == 'thought' else 'agent_message'
        if source == 'chunk':
            for part in parts:
                update(recorder, {'sessionUpdate': kind + '_chunk', 'messageId': 'm', 'content': part})
        else:
            update(recorder, {'sessionUpdate': kind, 'messageId': 'm', 'content': parts})
        update(recorder, {'sessionUpdate': 'state_update', 'state': 'idle'})
    content = next(r['content'] for r in records(recorder) if r['type'] in ('message', 'tool_result'))
    assert content[1] == {'type': 'org.agentsessionrecord.native/content',
                          '_meta': {'org.agentsessionrecord.native': {'native': native}}}
    assert content[0]['text'] == 'before' and content[2]['text'] == 'after'


def test_permission_options_cancel_and_unknown(capture):
    recorder = capture()
    tool(recorder, status='in_progress', name='run')
    for kind in ['allow_once', 'allow_always', 'reject_once', 'reject_always', 'future']:
        rpc(recorder, 'session/request_permission', {'sessionId': 's', 'subject': {'type': 'tool_call', 'toolCall': {'toolCallId': 'c'}}, 'options': [{'optionId': 'o', 'kind': kind}]}, {'result': {'outcome': {'outcome': 'selected', 'optionId': 'o'}}}, 'agent')
    rpc(recorder, 'session/request_permission', {'sessionId': 's', 'title': 'Host access', 'options': []}, {'result': {'outcome': {'outcome': 'cancelled'}}}, 'agent')
    approvals = [r for r in records(recorder) if r['type'] == 'approval']
    assert [r['decision'] for r in approvals] == ['approved', 'approved', 'denied', 'denied', 'cancelled']
    assert [r.get('scope') for r in approvals] == ['once', None, 'once', None, None]
    assert all('by' not in r and 'person' not in r for r in approvals)
    tool(recorder, status='completed')


def test_permission_without_subject_preserves_sourced_decision(capture):
    recorder = capture()
    rpc(recorder, 'session/request_permission', {
        'sessionId': 's', 'options': [{'optionId': 'o', 'kind': 'allow_once'}]},
        {'result': {'outcome': {'outcome': 'selected', 'optionId': 'o'}}}, 'agent')
    data = records(recorder)
    decision = next(r for r in data if r['type'] == 'approval')
    assert decision['decision'] == 'approved' and decision['scope'] == 'once'
    assert 'callId' not in decision and 'subject' not in decision and 'by' not in decision
    assert any('approval_subject' in r.get('missing', []) for r in data)


def test_completed_input_folding_and_diff(capture):
    recorder = capture()
    tool(recorder, name='edit', status='pending', rawInput={'partial': 1})
    assert len(records(recorder)) == 1
    tool(recorder, status='in_progress', rawInput=False, locations=[{'path': '/work/a', 'line': 1}])
    update(recorder, {'sessionUpdate': 'notice', 'content': [{'type': 'text', 'text': 'between'}]})
    tool(recorder, status='completed', rawInput=None, rawOutput='display fallback', content=[{'type': 'content', 'content': {'type': 'text', 'text': 'actual'}}, {'type': 'diff', 'changes': [{'operation': 'modify', 'path': '/work/a'}], 'patch': {'format': 'git_patch', 'text': '@@ -1 +1 @@\n-a\n+b\n'}}])
    data = records(recorder)
    call = next(r for r in data if r['type'] == 'tool_call')
    result = next(r for r in data if r['type'] == 'tool_result')
    change = next(r for r in data if r['type'] == 'file_change')
    assert call['input'] is False and result['input'] is None
    assert result['content'] == [{'type': 'text', 'text': 'actual'}]
    assert change['status'] == 'applied' and change['patch'].endswith('+b\n')
    assert [r['type'] for r in data] == ['session', 'tool_call', 'message', 'tool_result', 'file_change']


def test_prompt_acceptance_echo_and_no_guessed_authorship(capture):
    recorder = capture()
    rpc(recorder, 'session/prompt', {'sessionId': 's', 'prompt': [{'type': 'text', 'text': 'rejected'}]}, {'error': {'code': -1}})
    assert not recorder.sessions
    rpc(recorder, 'session/prompt', {'sessionId': 's', 'prompt': [{'type': 'text', 'text': 'accepted'}]}, {'result': {'messageId': 'p'}})
    update(recorder, {'sessionUpdate': 'user_message', 'messageId': 'p', 'content': [{'type': 'text', 'text': 'accepted'}]})
    update(recorder, {'sessionUpdate': 'state_update', 'state': 'idle'})
    messages = [r for r in records(recorder) if r['type'] == 'message']
    assert len(messages) == 1 and 'author' not in messages[0]


def test_settings_receiving_session_and_compaction(capture):
    recorder = capture(selectors={'mode': 'mode', 'permission': 'approval'})
    rpc(recorder, 'session/new', {'cwd': '/work'}, {'result': {'sessionId': 's', 'configOptions': [{'id': 'mode', 'currentValue': 'plan'}, {'id': 'unknown', 'currentValue': 'unsafe', 'category': 'permission'}]}})
    update(recorder, {'sessionUpdate': 'session_message', 'messageId': 'inter', 'senderSessionId': 'child:#', 'content': [{'type': 'text', 'text': 'report'}]})
    update(recorder, {'sessionUpdate': 'session_message', 'messageId': 'inter', 'senderSessionId': None})
    update(recorder, {'sessionUpdate': 'state_update', 'state': 'requires_action'})
    update(recorder, {'sessionUpdate': 'compaction_update', 'compactionId': 'co', 'status': 'completed', 'summary': [{'type': 'text', 'text': 'summary'}]})
    data = records(recorder)
    assert next(r for r in data if 'agentSettings' in r)['agentSettings'] == {'mode': 'plan'}
    inter = next(r for r in data if r.get('origin') == 'injected')
    assert inter['from'] == 'com.example.agent:child%3A%23'
    assert data[-2]['origin'] == 'compaction' and data[-1]['type'] == 'gap'


def test_replay_restart_late_update_and_historical_times(capture):
    recorder = capture()
    update(recorder, {'sessionUpdate': 'agent_message', 'messageId': 'm', 'content': [{'type': 'text', 'text': 'first'}]})
    update(recorder, {'sessionUpdate': 'state_update', 'state': 'idle'})
    original = recorder.sessions['s'].path.read_bytes()
    recorder.close()
    restarted = Recorder(recorder.directory, 'com.example.agent', clock=lambda: T)
    restarted.observe('client', {'id': 1, 'method': 'session/load', 'params': {'sessionId': 's'}})
    update(restarted, {'sessionUpdate': 'agent_message', 'messageId': 'm', 'content': [{'type': 'text', 'text': 'first'}]})
    restarted.observe('agent', {'id': 1, 'result': {}})
    assert restarted.sessions['s'].path.read_bytes() == original
    update(restarted, {'sessionUpdate': 'agent_message', 'messageId': 'm', 'content': [{'type': 'text', 'text': 'changed'}]})
    update(restarted, {'sessionUpdate': 'state_update', 'state': 'idle'})
    assert restarted.sessions['s'].path.read_bytes().startswith(original)
    assert len([r for r in records(restarted) if r['type'] == 'message']) == 1
    restarted.close()


def test_redaction_large_native_values_and_unknowns(capture):
    secret = 'synthetic-' + 'credential'
    recorder = capture(secrets=[secret])
    tool(recorder, name='test', status='completed', rawInput={'native': 9007199254740993, 'value': secret})
    update(recorder, {'sessionUpdate': 'future', 'token': secret})
    data = records(recorder)
    text = recorder.sessions['s'].path.read_text()
    assert secret not in text
    call = next(r for r in data if r['type'] == 'tool_call')
    assert call['input']['native'] == '9007199254740993' and call['truncated']
    assert not any(r['type'] == 'inference' for r in data)
    losses = {loss for row in data for loss in row.get('missing', [])}
    assert 'redacted_content' in losses and 'redacted' not in losses


def test_redacted_header_uses_content_loss_name(capture):
    secret = 'synthetic-private-version'
    recorder = capture(secrets=[secret])
    recorder.version = secret
    tool(recorder, name='test', status='completed')
    header = records(recorder)[0]
    assert header['truncated'] is True
    assert 'redacted_content' in header['missing'] and 'redacted' not in header['missing']
    assert secret not in recorder.sessions['s'].path.read_text()


def test_bidirectional_ids_and_explicit_close(capture):
    recorder = capture()
    recorder.observe('client', {'id': 1, 'method': 'session/new', 'params': {'cwd': '/work'}})
    recorder.observe('agent', {'id': 1, 'method': 'session/request_permission', 'params': {'sessionId': 's', 'title': 'Access', 'options': []}})
    recorder.observe('agent', {'id': 1, 'result': {'sessionId': 's'}})
    recorder.observe('client', {'id': 1, 'result': {'outcome': {'outcome': 'cancelled'}}})
    rpc(recorder, 'session/close', {'sessionId': 's'}, {'result': {}})
    data = records(recorder)
    assert data[0]['cwd'] == '/work'
    assert data[-2]['type'] == 'approval' and data[-1]['endedAt'] == T


def test_stdio_proxy_preserves_wire_and_exit(tmp_path):
    traffic = b'{"method":"ping","params":{"x":9007199254740993}}\n'
    echo = 'import sys; data=sys.stdin.buffer.read();sys.stdout.buffer.write(data);sys.exit(7)'
    result = subprocess.run([sys.executable, '-m', 'asr_acp.cli', '--agent', 'com.example.agent', '--output', str(tmp_path), '--', sys.executable, '-c', echo], input=traffic, capture_output=True, timeout=10)
    assert result.returncode == 7 and result.stdout == traffic


def test_stdio_proxy_preserves_oversized_malformed_and_incomplete_frames(tmp_path):
    traffic = b'x' * (16 * 1024 * 1024 + 1) + b'\n{bad}\r\n{"method":"ping"}\npartial'
    echo = 'import sys; data=sys.stdin.buffer.read();sys.stdout.buffer.write(data);sys.exit(7)'
    result = subprocess.run([sys.executable, '-m', 'asr_acp.cli', '--agent', 'com.example.agent', '--output', str(tmp_path), '--', sys.executable, '-c', echo], input=traffic, capture_output=True, timeout=15)
    assert result.returncode == 7 and result.stdout == traffic


def test_stdio_proxy_preserves_traffic_after_recording_failure(tmp_path):
    # The update lacks a required session key. Recording must stop, not the agent.
    traffic = b'{"method":"session/update","params":{}}\n{"method":"ping"}\n'
    echo = 'import sys; data=sys.stdin.buffer.read();sys.stdout.buffer.write(data);sys.exit(7)'
    result = subprocess.run([sys.executable, '-m', 'asr_acp.cli', '--agent', 'com.example.agent', '--output', str(tmp_path), '--', sys.executable, '-c', echo], input=traffic, capture_output=True, timeout=10)
    assert result.returncode == 7 and result.stdout == traffic


def test_stdio_proxy_preserves_traffic_when_storage_cannot_start(tmp_path):
    target = tmp_path / 'not-a-directory'
    target.write_bytes(b'synthetic-existing-file')
    traffic = b'{"synthetic":"unchanged"}\r\n'
    agent = 'import sys; sys.stdout.buffer.write(sys.stdin.buffer.read()); sys.exit(7)'
    result = subprocess.run([sys.executable, '-m', 'asr_acp.cli', '--agent', 'com.example.agent',
                             '--output', str(target), '--', sys.executable, '-c', agent],
                            input=traffic, capture_output=True, timeout=15)
    assert result.returncode == 7 and result.stdout == traffic
    assert result.stderr == b'ASR_ACP_CAPTURE_FAILED\n'
    assert target.read_bytes() == b'synthetic-existing-file'


def test_state_limit_stops_capture_with_gap_and_releases_pending_data(capture, monkeypatch):
    import asr_acp.recorder as module
    recorder = capture()
    update(recorder, {'sessionUpdate': 'notice', 'title': 'synthetic'})
    monkeypatch.setattr(module, 'MAX_CAPTURE_BYTES', recorder.observed_bytes + 1)
    recorder.observe('client', {'id': 2, 'method': 'session/prompt', 'params': {'sessionId': 's', 'prompt': []}})
    assert recorder.disabled and recorder.failures == 1
    assert not recorder.requests and not recorder.pending_fork_updates
    data = records(recorder)
    assert data[-1]['type'] == 'gap' and data[-1]['reason'] == 'not_recorded'
    assert any('capture_stopped' in r.get('missing', []) for r in data)
    before = recorder.sessions['s'].path.read_bytes()
    update(recorder, {'sessionUpdate': 'notice', 'title': 'later'})
    assert recorder.sessions['s'].path.read_bytes() == before


def test_storage_failure_disables_capture_without_raising(capture, monkeypatch):
    recorder = capture()
    update(recorder, {'sessionUpdate': 'notice', 'title': 'synthetic'})
    def broken(*args, **kwargs):
        raise OSError('synthetic')
    monkeypatch.setattr(recorder.sessions['s'].writer, 'append', broken)
    update(recorder, {'sessionUpdate': 'notice', 'title': 'later'})
    assert recorder.disabled


def test_interleaved_tools_chunks_clears_and_cancelled_reply(capture):
    recorder = capture()
    tool(recorder, name='execute', status='in_progress', rawInput={'command': 'echo a'})
    update(recorder, {'sessionUpdate': 'tool_call_content_chunk', 'toolCallId': 'c', 'content': {'type': 'content', 'content': {'type': 'text', 'text': 'a'}}})
    update(recorder, {'sessionUpdate': 'agent_message', 'messageId': 'm', 'content': [{'type': 'text', 'text': 'replace me'}], '_meta': {'a': {'x': 1}, 'b': True}})
    update(recorder, {'sessionUpdate': 'agent_message', 'messageId': 'm', 'content': None, '_meta': {'a': None}})
    update(recorder, {'sessionUpdate': 'agent_message_chunk', 'messageId': 'm', 'content': {'type': 'text', 'text': 'new'}})
    update(recorder, {'sessionUpdate': 'tool_call_content_chunk', 'toolCallId': 'c', 'content': {'type': 'content', 'content': {'type': 'text', 'text': 'b'}}})
    tool(recorder, status='completed')
    update(recorder, {'sessionUpdate': 'state_update', 'state': 'idle', 'stopReason': 'cancelled'})
    data = records(recorder)
    assert next(r for r in data if r['type'] == 'tool_result')['content'] == [{'type': 'text', 'text': 'ab'}]
    reply = next(r for r in data if r['type'] == 'message')
    assert reply['content'] == [{'type': 'text', 'text': 'new'}] and reply['status'] == 'interrupted'
    assert reply['_meta'][META]['source']['_meta'] == {'b': True}


def test_child_and_loaded_historical_items(capture):
    recorder = capture()
    update(recorder, {'sessionUpdate': 'subagent_update', 'sessionId': 'child'})
    recorder.observe('client', {'id': 4, 'method': 'session/load', 'params': {'sessionId': 'child'}})
    update(recorder, {'sessionUpdate': 'agent_message', 'messageId': 'historical', 'content': [{'type': 'text', 'text': 'history'}]}, sid='child')
    recorder.observe('agent', {'id': 4, 'result': {}})
    data = records(recorder, 'child')
    assert data[0]['parent'] == {'kind': 'subagent', 'session': 'com.example.agent:s'}
    assert 'ts' not in data[1]
    assert not any('endedAt' in r for r in data)


def test_malformed_and_abandoned_tool_does_not_invent_outcome(capture):
    recorder = capture()
    tool(recorder, name='incomplete', status='pending')
    recorder.malformed()
    recorder.close()
    data = records(recorder)
    assert any(r['type'] == 'gap' and r['reason'] == 'unparseable' for r in data)
    assert not any(r['type'] in ('tool_result', 'approval') for r in data)


def test_late_tool_content_stays_metadata(capture):
    recorder = capture()
    tool(recorder, name='execute', status='completed', content=[{'type': 'content', 'content': {'type': 'text', 'text': 'first'}}])
    original = recorder.sessions['s'].path.read_bytes()
    update(recorder, {'sessionUpdate': 'tool_call_content_chunk', 'toolCallId': 'c', 'content': {'type': 'content', 'content': {'type': 'text', 'text': 'late'}}})
    tool(recorder, status='in_progress')
    data = records(recorder)
    assert recorder.sessions['s'].path.read_bytes().startswith(original)
    assert len([r for r in data if r['type'] == 'tool_result']) == 1
    assert data[-1]['_meta'][META]['lateUpdate']['status'] == 'in_progress'


def test_sigterm_stops_the_owned_agent(tmp_path):
    import os
    import signal
    agent = 'import os,sys; print(os.getpid(),flush=True);sys.stdin.read()'
    process = subprocess.Popen([sys.executable, '-m', 'asr_acp.cli', '--agent', 'com.example.agent', '--output', str(tmp_path), '--', sys.executable, '-c', agent], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    child = int(process.stdout.readline())
    try:
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 143 and b'ASR_ACP_STOPPED' in stderr
        with pytest.raises(ProcessLookupError):
            os.kill(child, 0)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_fork_replay_keeps_copies_without_credit(capture):
    recorder = capture()
    recorder.observe('client', {'id': 1, 'method': 'session/fork', 'params': {'sessionId': 'parent'}})
    update(recorder, {'sessionUpdate': 'agent_message', 'messageId': 'inherited', 'content': [{'type': 'text', 'text': 'old'}]}, sid='fork')
    assert 'fork' not in recorder.sessions
    recorder.observe('agent', {'id': 1, 'result': {'sessionId': 'fork'}})
    update(recorder, {'sessionUpdate': 'state_update', 'state': 'idle'}, sid='fork')
    update(recorder, {'sessionUpdate': 'agent_message', 'messageId': 'new', 'content': [{'type': 'text', 'text': 'new'}]}, sid='fork')
    update(recorder, {'sessionUpdate': 'state_update', 'state': 'idle'}, sid='fork')
    data = records(recorder, 'fork')
    assert data[0]['parent'] == {'session': 'com.example.agent:parent', 'kind': 'fork'}
    assert data[1]['copiedFrom'] == {'session': 'com.example.agent:parent'} and 'ts' not in data[1]
    assert 'copiedFrom' not in data[2] and data[2]['ts'] == T


def test_repository_facts_only_on_creation_not_historical_load(capture, tmp_path):
    subprocess.run(['git', '-C', str(tmp_path), 'init', '-q', '-b', 'initial'], check=True)
    recorder = capture()
    rpc(recorder, 'session/new', {'cwd': str(tmp_path)}, {'result': {'sessionId': 's'}})
    assert records(recorder)[0]['repos'][0] == {'path': str(tmp_path), 'branch': 'initial'}
    historical = capture()
    rpc(historical, 'session/load', {'cwd': str(tmp_path), 'sessionId': 's'}, {'result': {}})
    assert 'cwd' not in records(historical)[0]
    assert 'repos' not in records(historical)[0]
