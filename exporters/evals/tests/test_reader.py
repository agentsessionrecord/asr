from copy import deepcopy
from decimal import Decimal

import pytest

from asr_evals.jsonio import dumps
from asr_evals.model import audit, interval, observations, timestamp_ns
from asr_evals.reader import Session, load_sessions, read_annotations, read_session
from conftest import FIXTURES


def test_copies_usage_and_scoped_totals(session):
    result = session.accounting()
    assert result["inferences"] == 2
    assert result["known_usage_sums"]["inputTokens"] == 100
    assert result["known_usage_sums"]["outputTokens"] == 20
    assert result["known_usage_sums"]["cacheReadTokens"] == 40
    assert result["cost_by_model_currency"][0]["amount"] == Decimal("0.123456789012345678901")
    assert result["cost_by_model_currency"][1]["amount"] == 0
    assert session.missing == {"reasoning", "approvals"}


def test_settings_replacement_clearing_and_offered_tools(session):
    settings = session.settings["settings-2"]
    assert "asks" not in settings
    assert settings["approval"] == "ask"
    assert settings["modelSettings"] == {"maxOutputTokens": 0}
    assert settings["externalSandbox"] == {}
    assert session.tools["settings-2"] == []
    assert session.effective_input(session.by_id["edit-call"]) == {"input": None}


def test_pairing_uses_whole_file_and_ignores_proximity(session):
    records = deepcopy(session.records)
    records.append(dict(session.by_id["test-call"], id="duplicate-call"))
    ambiguous = Session(session.header, records, "synthetic")
    assert ambiguous.result(ambiguous.by_id["test-call"]) is None
    assert ambiguous.call("test-1") is None
    view = audit([ambiguous])
    assert any(u["code"] == "call" for u in view["unresolved"])
    assert next(r for r in view["sessions"][0]["records"] if r["id"] == "test-call")["outcome"] == "unknown"


def test_recovery_duplicate_keys_utf8_incomplete_tail_and_number_precision(tmp_path, session):
    path = tmp_path / "recovery.jsonl"
    header = dumps(session.header).encode() + b"\n"
    good = b'{"type":"tool_call","id":"large","callId":"native","input":{"integer":9007199254740993,"fraction":1.000000000000000000001}}\n'
    path.write_bytes(header + b'{"type":"gap","type":"message"}\n\xff\n' + good + b'{"type":"message","id":"tail"}')
    recovered = read_session(path)
    assert [r["id"] for r in recovered.records] == ["large"]
    assert [d["code"] for d in recovered.diagnostics] == ["malformed_line", "malformed_line", "incomplete_tail"]
    assert "9007199254740993" in dumps(recovered.records)
    assert "1.000000000000000000001" in dumps(recovered.records)


def test_file_order_and_forward_inference_link(session):
    items = audit([session])["sessions"][0]["records"]
    assert items[0]["line"] == 2
    ids = [r["id"] for r in items]
    assert ids.index("linked-output") < ids.index("infer:1")
    assert not any(u["code"] == "inference" for u in audit([session])["unresolved"])
    call = deepcopy(session.by_id["edit-call"])
    call["ts"] = "2026-10-31T12:00:30Z"
    other = Session(session.header, [call] + session.records[7:], "synthetic")
    assert interval(other, other.header) is None


def test_unknown_types_are_ignored_and_unknown_status_stays_open(session):
    records = deepcopy(session.records)
    records.append({"type": "com.example.extension/future", "id": "unknown", "secret": "UNKNOWN_SENTINEL"})
    records.append({"type": "tool_result", "id": "unpaired", "status": "_future"})
    other = Session(session.header, records, "synthetic")
    assert "UNKNOWN_SENTINEL" not in dumps(audit([other]))
    assert audit([other])["sessions"][0]["records"][-1]["status"] == "_future"


def test_child_copied_prefix_and_unavailable_related_session(session):
    child = read_session(FIXTURES / "child.jsonl")
    assert child.accounting()["known_usage_sums"] == {"inputTokens": 5, "outputTokens": 2}
    assert "inherited" in child.copied
    parent_only = audit([child])
    assert parent_only["unresolved"][0]["code"] == "related_session"
    linked = audit([session, child])
    assert len(linked["relationships"]) == 1
    assert linked["relationships"][0]["call_id"] == "spawn-1"


def test_reference_escaping_and_export_deduplication(session):
    assert session.ref == "com.example.agent:synthetic%20space:eval%3A7"
    assert session.cite(session.by_id["prompt #1"]).endswith("#prompt%20%231")
    assert len(load_sessions([FIXTURES / "session.jsonl"] * 2)) == 1


def test_shared_producer_references_resolve_across_observability_exports(session):
    from agent_session_record import session_reference

    parent_header = deepcopy(session.header)
    parent_header['sessionId'] = 'run/é: #%\x85'
    parent = Session(parent_header, [], 'synthetic-parent')
    child_header = deepcopy(session.header)
    child_header['parent'] = {'session': session_reference(
        parent_header['agent']['name'], parent_header['sessionId'], namespace=parent_header['namespace']),
        'kind': 'subagent'}
    child = Session(child_header, [], 'synthetic-child')
    assert not audit([parent, child])['unresolved']
    assert audit([parent, child])['relationships'][0]['parent'] == parent.ref
    assert parent.cite({'id': 'record/é: #'}) == parent.ref + '#record/é%3A%20%23'


def test_timestamp_contract_is_explicit_and_zero_duration_is_real(session):
    assert interval(session, session.by_id["infer:1"]) is None
    assert interval(session, session.by_id["test-call"]) is None
    timed = interval(session, session.by_id["infer-2"], "end")
    assert timed["start"] == timed["end"]
    assert timestamp_ns("2026-10-31T12:00:00.123456789Z") % 1_000_000_000 == 123456789
    assert timestamp_ns("2026-10-31T12:00:00") is None


def test_annotations_supersedes_before_timestamp_order():
    annotations, diagnostics = read_annotations([FIXTURES / "tests.annotations.jsonl"])
    assert not diagnostics
    assert [a["id"] for a in annotations] == ["test-corrected", "test-extra"]


def test_cycle_cannot_create_parentage(session):
    records = [dict(session.by_id["edit-call"], parentCallId="test-1"),
               dict(session.by_id["test-call"], parentCallId="edit-1")]
    other = Session(session.header, records, "synthetic")
    items = observations(other)
    assert any("asr.unresolved_parent" in o["metadata"] for o in items)


def test_conflicting_exports_refused(tmp_path):
    source = FIXTURES / "session.jsonl"
    path = tmp_path / "different.jsonl"
    path.write_bytes(source.read_bytes() + b'{"type":"gap","id":"extra","reason":"unknown"}\n')
    with pytest.raises(ValueError, match="conflicting_session_exports"):
        load_sessions([source, path])


def test_malformed_record_shape_recovers_without_trusting_nested_values(tmp_path, session):
    path = tmp_path / "shapes.jsonl"
    path.write_text(dumps(session.header) + '\n{"type":"inference","id":"invalid","usage":[]}\n'
                    '{"type":"gap","id":"good","reason":"unknown"}\n')
    recovered = read_session(path)
    assert [r["id"] for r in recovered.records] == ["good"]
    assert recovered.diagnostics == [{"line": 2, "code": "invalid_record_shape"}]


def test_record_only_copy_does_not_guess_source_session(session):
    copied = dict(session.by_id["infer:1"], id="copy-record", copiedFrom={"record": "infer:1"})
    other = Session(session.header, session.records + [copied], "synthetic")
    assert not other.original(copied)
    assert any(u["code"] == "copy_source_session_unknown" for u in audit([other])["unresolved"])


def test_subagent_links_combine_result_and_child_sides(session):
    child = read_session(FIXTURES / "child.jsonl")
    records = session.records + [
        {"type": "tool_call", "id": "spawn", "callId": "spawn-1", "name": "start_agent"},
        {"type": "tool_result", "id": "spawn-result", "callId": "spawn-1", "status": "completed", "subagent": {"session": child.ref}},
    ]
    parent = Session(session.header, records, "synthetic")
    view = audit([parent, child])
    assert view["relationships"] == [{"parent": session.ref, "call_id": "spawn-1", "child": child.ref}]
    assert not any(u["code"] in ("related_session", "parent_call") for u in view["unresolved"])
    assert any(u["code"] == "related_session" for u in audit([parent])["unresolved"])
