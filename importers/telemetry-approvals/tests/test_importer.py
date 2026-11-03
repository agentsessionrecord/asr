from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from agent_session_record import Writer
from asr_telemetry_approvals import import_approvals
from asr_telemetry_approvals.importer import META
from asr_telemetry_approvals.telemetry import documents, events

FIXTURES = Path(__file__).parent / 'fixtures'


def make_source(tmp_path, agent='codex', calls=('c1',), extra=(), missing=None, **fields):
    path = tmp_path / 'input.asr.jsonl'
    with Writer(path, {'agent': {'name': agent, 'version': '0.163.0' if agent == 'codex' else '2.1.305'},
                       'sessionId': 'synthetic-session', 'producer': {'name': 'fixture', 'version': '1', 'method': 'native'},
                       'missing': ['approvals', 'usage'] if missing is None else missing, **fields}) as writer:
        for i, call in enumerate(calls):
            writer.append({'type': 'tool_call', 'id': f'call-{i}', 'callId': call, 'name': 'shell'})
            writer.append({'type': 'message', 'id': f'notice-{i}', 'role': 'user', 'author': 'harness', 'content': []})
            writer.append({'type': 'tool_result', 'id': f'result-{i}', 'callId': call, 'status': 'unknown'})
        for row in extra:
            writer.append(row)
    return path


def telemetry(tmp_path, decisions, agent='codex', **attributes):
    rows = []
    for i, item in enumerate(decisions):
        attrs = {'conversation.id' if agent == 'codex' else 'session.id': 'synthetic-session',
                 'call_id' if agent == 'codex' else 'tool_use_id': 'c1', **attributes, **item}
        rows.append({'body': f'{"codex" if agent == "codex" else "claude_code"}.tool_decision', 'attributes': attrs})
    path = tmp_path / 'telemetry.json'
    path.write_text(json.dumps(rows))
    return path


def run(tmp_path, source, logs, name='output.asr.jsonl'):
    output = tmp_path / name
    summary = import_approvals(source, [logs], output)
    return [json.loads(line) for line in output.read_text().splitlines()], summary, output


def approvals(rows):
    return [r for r in rows if r['type'] == 'approval']


@pytest.mark.parametrize(('native', 'decision', 'scope'), [
    ('approved', 'approved', 'once'), ('approved_for_session', 'approved', 'session'),
    ('approved_with_amendment', 'approved', 'always'), ('approved_mcp_policy_amendment', 'approved', 'always'),
    ('approved_with_network_policy_allow', 'approved', 'always'), ('denied_with_network_policy_deny', 'denied', None),
    ('denied', 'denied', None), ('abort', 'denied', None), ('timed_out', 'cancelled', None),
])
def test_codex_decisions_and_lifetimes(tmp_path, native, decision, scope):
    source = make_source(tmp_path)
    logs = telemetry(tmp_path, [{'decision': native, 'source': 'Config'}])
    rows, summary, output = run(tmp_path, source, logs)
    approval, = approvals(rows)
    assert approval['decision'] == decision
    assert approval.get('scope') == scope
    assert approval['by'] == 'policy'
    assert 'ts' not in approval
    assert rows.index(approval) + 1 == next(i for i, r in enumerate(rows) if r['type'] == 'tool_result')
    assert summary['complete'] and 'approvals' in rows[0]['missing']
    assert rows[0]['derivedFrom']['sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert rows[0]['producer']['method'] == 'converter'
    assert output.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(('source', 'by'), [('User', 'user'), ('Config', 'policy'), ('AutomatedReviewer', 'classifier'), ('Hook', None), ('Future', None)])
def test_codex_deciders_are_not_guessed(tmp_path, source, by):
    native = make_source(tmp_path)
    logs = telemetry(tmp_path, [{'decision': 'denied', 'source': source}])
    rows, _, _ = run(tmp_path, native, logs)
    assert approvals(rows)[0].get('by') == by


@pytest.mark.parametrize(('decision', 'source', 'extra', 'expected', 'by', 'scope'), [
    ('accept', 'config', {}, 'approved', 'policy', None),
    ('reject', 'config', {}, 'denied', 'policy', None),
    ('reject', 'user_abort', {}, 'cancelled', None, None),
    ('reject', 'user_reject', {}, 'denied', 'user', None),
    ('accept', 'hook', {}, 'approved', 'hook', None),
    ('reject', 'config', {'classifier_verdict': 'block'}, 'denied', 'classifier', None),
    ('reject', 'config', {'classifier_verdict': 'unavailable'}, 'denied', 'classifier', None),
    ('accept', 'config', {'reasonType': 'mode'}, 'approved', 'mode', None),
    ('accept', 'user_temporary', {}, 'approved', None, None),
    ('accept', 'user_permanent', {}, 'approved', None, 'always'),
])
def test_claude_does_not_invent_fresh_answers(tmp_path, decision, source, extra, expected, by, scope):
    native = make_source(tmp_path, 'claude-code')
    logs = telemetry(tmp_path, [{'decision': decision, 'source': source, **extra}], 'claude-code')
    rows, _, _ = run(tmp_path, native, logs)
    record, = approvals(rows)
    assert (record['decision'], record.get('by'), record.get('scope')) == (expected, by, scope)
    assert 'person' not in record


def test_grant_scope_requires_an_unambiguous_correlated_safety_event(tmp_path):
    source = make_source(tmp_path, 'claude-code')
    logs = telemetry(tmp_path, [{'decision': 'accept', 'source': 'user_temporary'}], 'claude-code')
    data = json.loads(logs.read_text())
    safety = {'body': 'claude_code.safety_event', 'attributes': {'session.id': 'synthetic-session', 'tool_use_id': 'c1',
              'decision': 'accept', 'decision_source': 'user_temporary', 'grant_scope': 'session'}}
    data.append(safety)
    logs.write_text(json.dumps(data))
    rows, _, _ = run(tmp_path, source, logs)
    assert approvals(rows)[0]['scope'] == 'session'
    data.insert(1, deepcopy(data[0]))
    logs.write_text(json.dumps(data))
    rows, _, _ = run(tmp_path, source, logs, 'repeat.asr.jsonl')
    assert len(approvals(rows)) == 2
    assert all('scope' not in r for r in approvals(rows))


def test_repeated_decisions_preserve_source_order_without_sorting_times(tmp_path):
    source = make_source(tmp_path)
    logs = telemetry(tmp_path, [
        {'decision': 'denied', 'source': 'AutomatedReviewer', 'event.timestamp': '2026-10-31T12:00:02Z'},
        {'decision': 'approved_for_session', 'source': 'User', 'event.timestamp': '2026-10-31T12:00:01Z'},
    ])
    rows, _, output = run(tmp_path, source, logs)
    assert [r['decision'] for r in approvals(rows)] == ['denied', 'approved']
    assert rows[-3:-1] == approvals(rows)
    again, summary, _ = run(tmp_path, output, logs, 'again.asr.jsonl')
    assert summary['inserted'] == 0
    assert [r['id'] for r in approvals(rows)] == [r['id'] for r in approvals(again)]


def test_partial_coverage_retains_missing_in_header_and_updates(tmp_path):
    source = make_source(tmp_path, calls=('c1', 'c2'), missing=[], extra=[{'type': 'session_info', 'id': 'loss', 'missing': ['approvals', 'tools']}])
    logs = telemetry(tmp_path, [{'decision': 'approved'}])
    rows, summary, _ = run(tmp_path, source, logs)
    assert not summary['complete']
    assert rows[0]['missing'] == ['approvals']
    assert rows[-1]['missing'] == ['approvals', 'tools']
    logs = telemetry(tmp_path, [{'decision': 'approved'}, {'decision': 'denied', 'call_id': 'c2'}])
    rows, summary, _ = run(tmp_path, source, logs, 'full.asr.jsonl')
    assert summary['complete'] and rows[-1]['missing'] == ['approvals', 'tools']


def test_unmatched_decisions_stay_in_metadata(tmp_path):
    source = make_source(tmp_path)
    logs = telemetry(tmp_path, [{'decision': 'approved', 'call_id': 'absent'}])
    rows, summary, _ = run(tmp_path, source, logs)
    assert not approvals(rows)
    assert summary['unpositioned'] == 1 and not summary['complete']
    assert rows[0]['_meta'][META]['unpositioned'][0]['approval']['callId'] == 'absent'
    assert 'approvals' in rows[0]['missing']


def test_call_without_result_is_not_given_a_snapshot_position(tmp_path):
    source = make_source(tmp_path, calls=(), extra=[{'type': 'tool_call', 'id': 'call', 'callId': 'c1', 'name': 'shell'}])
    logs = telemetry(tmp_path, [{'decision': 'abort'}])
    rows, summary, _ = run(tmp_path, source, logs)
    assert summary['unpositioned'] == 1 and not approvals(rows)


def test_duplicate_call_identity_is_not_paired(tmp_path):
    source = make_source(tmp_path, extra=[{'type': 'tool_call', 'id': 'other', 'callId': 'c1', 'name': 'shell'}])
    logs = telemetry(tmp_path, [{'decision': 'approved'}])
    rows, summary, _ = run(tmp_path, source, logs)
    assert not summary['complete'] and not approvals(rows)


def test_other_sessions_agents_and_parent_ids_do_not_join(tmp_path):
    source = make_source(tmp_path)
    logs = telemetry(tmp_path, [{'decision': 'approved', 'conversation.id': 'other', 'session.id': 'synthetic-session'}])
    rows, summary, _ = run(tmp_path, source, logs)
    assert not summary['coveredCalls'] and not approvals(rows)
    data = [{'body': 'claude_code.tool_decision', 'attributes': {'session.id': 'synthetic-session', 'tool_use_id': 'c1', 'decision': 'accept'}}]
    logs.write_text(json.dumps(data))
    assert not approvals(run(tmp_path, source, logs, 'other.asr.jsonl')[0])


def test_claude_child_identity_and_namespaces(tmp_path):
    source = make_source(tmp_path, 'claude-code', namespace='synthetic-install')
    logs = telemetry(tmp_path, [{'decision': 'accept', 'agent_id': 'child', 'session.namespace': 'synthetic-install'}], 'claude-code')
    assert not approvals(run(tmp_path, source, logs)[0])
    logs = telemetry(tmp_path, [{'decision': 'accept', 'session.namespace': 'synthetic-install'}], 'claude-code')
    assert len(approvals(run(tmp_path, source, logs, 'matched.asr.jsonl')[0])) == 1


def test_transcript_telemetry_duplicates_are_enriched_once(tmp_path):
    source = make_source(tmp_path, extra=[{'type': 'approval', 'id': 'native-decision', 'callId': 'c1',
        'decision': 'approved', 'native': {'decision': 'approved', 'source': 'User'}}])
    logs = telemetry(tmp_path, [{'decision': 'approved', 'source': 'User'}])
    rows, summary, output = run(tmp_path, source, logs)
    assert summary['reconciled'] == 1 and summary['inserted'] == 0
    record, = approvals(rows)
    assert record['id'] == 'native-decision' and record['scope'] == 'once' and record['by'] == 'user'
    assert import_approvals(output, [logs], tmp_path / 'again.asr.jsonl')['inserted'] == 0


def test_unknown_versions_and_decisions_are_preserved_as_unknown(tmp_path):
    source = make_source(tmp_path)
    logs = telemetry(tmp_path, [{'decision': 'future_decision'}])
    rows, summary, _ = run(tmp_path, source, logs)
    assert not approvals(rows) and not summary['complete']
    assert rows[0]['_meta'][META]['unpositioned'][0]['native']['decision'] == 'future_decision'
    logs = telemetry(tmp_path, [{'decision': 'approved', 'app.version': '9.0.0'}])
    assert not approvals(run(tmp_path, source, logs, 'unknown.asr.jsonl')[0])


def test_existing_records_unknown_fields_and_exact_numbers_are_preserved(tmp_path):
    source = make_source(tmp_path)
    raw = source.read_bytes().replace(b'"missing":', b'"unfamiliar":{"decimal":1.000000000000000000001},"missing":', 1)
    raw += b'{"type":"com.example/future","id":"future","value":0.100000000000000000001,"large":9007199254740993}\n'
    source.write_bytes(raw)
    logs = telemetry(tmp_path, [{'decision': 'approved'}])
    _, _, output = run(tmp_path, source, logs)
    assert b'1.000000000000000000001' in output.read_bytes()
    assert output.read_bytes().endswith(raw.splitlines(keepends=True)[-1])


def test_corrupt_and_incomplete_asr_records_create_gaps_and_do_not_clear_loss(tmp_path):
    source = make_source(tmp_path)
    source.rename(tmp_path / 'original.txt')
    source.write_bytes((tmp_path / 'original.txt').read_bytes() + b'{broken}\n{"type":"message"}')
    logs = telemetry(tmp_path, [{'decision': 'approved'}])
    rows, summary, _ = run(tmp_path, source, logs)
    assert summary['gaps'] == 2 and not summary['complete']
    assert [r['type'] for r in rows[-2:]] == ['gap', 'gap']
    source.unlink()  # Deliberately invalid input is not an ASR output.


def test_secret_bearing_telemetry_fields_are_excluded(tmp_path):
    source = make_source(tmp_path)
    logs = telemetry(tmp_path, [{'decision': 'approved', 'prompt': 'private synthetic text', 'user.account_id': 'synthetic-account', 'tool_input': 'private synthetic arguments'}])
    _, _, output = run(tmp_path, source, logs)
    assert 'private synthetic' not in output.read_text()
    assert 'synthetic-account' not in output.read_text()


def test_invalid_telemetry_is_rejected_before_output(tmp_path):
    source = make_source(tmp_path)
    logs = tmp_path / 'invalid.txt'
    for text in ['{"attributes":{"decision":"approved","decision":"denied"}}', '{attributes: process.exit(0)}', '{attributes: [Function]}', '{incomplete']:
        logs.write_text(text)
        with pytest.raises(ValueError):
            import_approvals(source, [logs], tmp_path / 'rejected.asr.jsonl')
        assert not (tmp_path / 'rejected.asr.jsonl').exists()


def test_new_output_only_and_deterministic_bytes(tmp_path):
    source = make_source(tmp_path)
    before = source.read_bytes()
    logs = telemetry(tmp_path, [{'decision': 'approved'}])
    _, _, output = run(tmp_path, source, logs)
    _, _, other = run(tmp_path, source, logs, 'other.asr.jsonl')
    assert output.read_bytes() == other.read_bytes() and source.read_bytes() == before
    with pytest.raises(FileExistsError):
        import_approvals(source, [logs], source)
    with pytest.raises(FileExistsError):
        import_approvals(source, [logs], output)


def test_otlp_and_console_native_fixtures(tmp_path):
    for agent, fixture in [('claude-code', 'claude-console.txt'), ('codex', 'codex-otlp.json')]:
        source = make_source(tmp_path, agent)
        rows, summary, _ = run(tmp_path, source, FIXTURES / fixture, f'{agent}.asr.jsonl')
        assert len(approvals(rows)) == 2 and summary['complete']
        source.unlink()


def test_cli(tmp_path):
    source = make_source(tmp_path)
    logs = telemetry(tmp_path, [{'decision': 'approved'}])
    output = tmp_path / 'cli.asr.jsonl'
    result = subprocess.run([sys.executable, '-m', 'asr_telemetry_approvals', str(source), '--telemetry', str(logs), '--output', str(output)], capture_output=True, text=True)
    assert result.returncode == 0 and json.loads(result.stdout)['inserted'] == 1


def test_rust_event_name_is_a_callsite_not_the_business_event(tmp_path):
    source = make_source(tmp_path)
    logs = telemetry(tmp_path, [{'decision': 'approved', 'source': 'Config'}])
    data = json.loads(logs.read_text())
    data[0]['eventName'] = 'event src/events/session_telemetry.rs:1217'
    data[0]['attributes']['event.name'] = 'codex.tool_decision'
    logs.write_text(json.dumps(data))
    assert len(approvals(run(tmp_path, source, logs)[0])) == 1


def test_inherited_gaps_prevent_a_false_completeness_claim(tmp_path):
    source = make_source(tmp_path, extra=[{'type': 'gap', 'id': 'history-loss', 'reason': 'not_retained'}])
    logs = telemetry(tmp_path, [{'decision': 'approved'}])
    rows, summary, _ = run(tmp_path, source, logs)
    assert not summary['complete'] and 'approvals' in rows[0]['missing']


def test_partial_telemetry_transport_duplicates_need_recorded_identity(tmp_path):
    source = make_source(tmp_path)
    data = {'decision': 'approved', 'event.sequence': '7', 'event.timestamp': '2026-10-31T12:00:00Z'}
    logs = telemetry(tmp_path, [data, data])
    assert len(approvals(run(tmp_path, source, logs)[0])) == 1


def test_more_precise_transcript_decider_is_not_duplicated(tmp_path):
    source = make_source(tmp_path, 'claude-code', extra=[{'type': 'approval', 'id': 'mode-decision', 'callId': 'c1',
        'decision': 'approved', 'by': 'mode', 'native': {'decision': 'accept', 'source': 'config', 'reasonType': 'mode'}}])
    logs = telemetry(tmp_path, [{'decision': 'accept', 'source': 'config'}], 'claude-code')
    rows, summary, _ = run(tmp_path, source, logs)
    assert summary['reconciled'] == 1
    assert len(approvals(rows)) == 1 and approvals(rows)[0]['by'] == 'mode'


def test_schema_invalid_complete_lines_become_gaps(tmp_path):
    source = make_source(tmp_path)
    source.rename(tmp_path / 'original.txt')
    source.write_bytes((tmp_path / 'original.txt').read_bytes() + b'{"type":"tool_call","id":"missing-call"}\n')
    logs = telemetry(tmp_path, [{'decision': 'approved'}])
    rows, summary, _ = run(tmp_path, source, logs)
    assert summary['gaps'] == 1 and rows[-1]['type'] == 'gap'
    source.unlink()


def test_nanosecond_event_time_and_observed_time_are_distinct(tmp_path):
    source = make_source(tmp_path)
    logs = tmp_path / 'otlp.json'
    data = {'eventName': 'codex.tool_decision', 'timeUnixNano': '1793448000000000001', 'observedTimeUnixNano': '1793448009999999999',
            'attributes': {'conversation.id': 'synthetic-session', 'call_id': 'c1', 'decision': 'approved'}}
    logs.write_text(json.dumps(data))
    assert approvals(run(tmp_path, source, logs)[0])[0]['ts'] == '2026-10-31T12:00:00.000000001Z'


@pytest.mark.parametrize(('agent', 'fixture'), [('claude-code', 'claude-console.txt'), ('codex', 'codex-otlp.json')])
def test_committed_mapping_samples_are_exact(tmp_path, agent, fixture):
    source = FIXTURES / f'{agent}.input.asr.jsonl'
    output = tmp_path / 'sample.asr.jsonl'
    import_approvals(source, [FIXTURES / fixture], output)
    assert output.read_bytes() == (FIXTURES / f'{agent}.expected.asr.jsonl').read_bytes()


def test_safety_otlp_fixture(tmp_path):
    source = make_source(tmp_path, 'claude-code')
    rows, summary, _ = run(tmp_path, source, FIXTURES / 'claude-safety-otlp.json')
    record, = approvals(rows)
    assert summary['complete'] and record['scope'] == 'session' and 'by' not in record


def test_large_native_values_and_empty_input(tmp_path):
    source = make_source(tmp_path)
    logs = telemetry(tmp_path, [{'decision': 'approved', 'event.sequence': 9007199254740993}])
    rows, _, _ = run(tmp_path, source, logs)
    assert approvals(rows)[0]['native']['event.sequence'] == '9007199254740993'
    empty = tmp_path / 'empty.txt'
    empty.write_bytes(b'')
    with pytest.raises(ValueError, match='empty'):
        import_approvals(empty, [logs], tmp_path / 'rejected.asr.jsonl')


def test_permission_creation_does_not_depend_on_umask(tmp_path):
    import os
    source = make_source(tmp_path)
    logs = telemetry(tmp_path, [{'decision': 'approved'}])
    previous = os.umask(0)
    try:
        _, _, output = run(tmp_path, source, logs)
    finally:
        os.umask(previous)
    assert output.stat().st_mode & 0o777 == 0o600


def test_loss_union_includes_updates_after_an_inference(tmp_path):
    source = make_source(tmp_path)
    with source.open('ab') as stream:
        stream.write(b'{"type":"inference","id":"unknown-model"}\n')
        stream.write(b'{"type":"session_info","id":"later-loss","missing":["model"]}\n')
    logs = telemetry(tmp_path, [{'decision': 'approved'}])
    rows, _, _ = run(tmp_path, source, logs)
    assert rows[-1]['missing'] == ['model']
