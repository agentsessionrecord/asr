from decimal import Decimal
from pathlib import Path
import subprocess

import duckdb
import pyarrow.parquet as pq
import pytest
import simplejson as json

from asr_tables import export
from asr_tables.cli import main
from asr_tables.export import money, update_settings
from asr_tables.loaders import load_duckdb
from asr_tables.reader import ExportError, encode_component
from asr_tables.schema import SCHEMAS

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"


def rows(dataset, table):
    return pq.read_table(dataset / (table + ".parquet")).to_pylist()


@pytest.fixture
def dataset(tmp_path):
    output = tmp_path / "tables"
    export(sorted(FIXTURES.glob("*.jsonl")), output)
    return output


def test_schema_empty_tables_and_permissions(tmp_path):
    output = tmp_path / "empty"
    export([], output)
    assert output.stat().st_mode & 0o777 == 0o700
    for name, schema in SCHEMAS.items():
        table = pq.read_table(output / (name + ".parquet"))
        assert table.num_rows == 0
        assert table.schema == schema
        assert (output / (name + ".parquet")).stat().st_mode & 0o777 == 0o600


def test_original_accounting_and_latest_totals(dataset, tmp_path):
    database = tmp_path / "tables.duckdb"
    load_duckdb(dataset, database)
    with duckdb.connect(str(database)) as connection:
        assert connection.execute("SELECT sum(input_tokens), sum(output_tokens) FROM inferences WHERE original").fetchone() == (130, 50)
        assert connection.execute("SELECT sum(cost_amount) FROM inferences WHERE original AND cost_currency='USD'").fetchone() == (Decimal("0.13"),)
        assert connection.execute("SELECT count(*) FROM inferences WHERE original AND cost_amount_text IS NULL").fetchone() == (1,)
        for query in (HERE.parent / "queries").glob("*.sql"):
            assert connection.execute(query.read_text()).fetchall()
    parent = next(row for row in rows(dataset, "sessions") if row["session_id"] == "tables:parent")
    assert json.loads(parent["latest_usage_json"]) == {"inputTokens": 1000, "includesSubagents": True}
    assert json.loads(parent["latest_cost_json"])["amount"] == 30
    assert parent["includes_subagents"] is True
    assert json.loads(parent["missing_json"]) == ["approvals", "timestamps"]
    assert parent["ended_at"] is None
    assert parent["user_id"] == "synthetic-user"
    assert json.loads(parent["tools_json"]) == []


def test_calls_results_and_approvals_pair_conservatively(dataset):
    calls = {row["record_id"]: row for row in rows(dataset, "tool_calls")}
    assert calls["call"]["outcome"] == "completed"
    assert calls["call"]["effective_input_json"] == "null"
    assert calls["call"]["effective_input_text"] is None
    assert calls["call"]["result_content_json"] == "[]"
    assert calls["call"]["duration_ms_text"] == "0"
    assert calls["unfinished"]["outcome"] == "unknown"
    assert calls["unfinished"]["input_text"] == ""
    for ident in ("call-1", "call-2"):
        assert calls[ident]["pairing"] == "ambiguous"
        assert calls[ident]["result_record_id"] is None
        assert calls[ident]["outcome"] == "unknown"
    results = {row["record_id"]: row for row in rows(dataset, "tool_results")}
    assert results["unpaired-result"]["paired_call_record_id"] is None
    assert results["orphan"]["pairing"] == "unpaired"
    approvals = {row["record_id"]: row for row in rows(dataset, "approvals")}
    assert approvals["decision"]["paired_call_record_id"] is None
    assert approvals["approval"]["paired_call_record_id"] == "call"


def test_copy_prefix_and_individual_copy(dataset):
    child = [row for row in rows(dataset, "records") if row["session_ref"].endswith("tables%3Achild")]
    assert [row["original"] for row in child] == [True, False, False, True, False, True, True]
    assert rows(dataset, "gaps")[0]["count"] == 0


def test_order_exact_json_unknown_data_and_links(dataset):
    records = rows(dataset, "records")
    prompt = next(row for row in records if row["record_id"] == "prompt 1")
    call = next(row for row in records if row["record_id"] == "call")
    assert prompt["position"] < call["position"] and prompt["ts"] > call["ts"]
    assert prompt["record_ref"].endswith("#prompt%201")
    future = next(row for row in records if row["record_id"] == "future")
    assert "0.123456789012345678901234567890" in future["raw_json"]
    assert json.loads(future["raw_json"], use_decimal=True)["futureField"]["enabled"] is False
    precise = next(row for row in rows(dataset, "inferences") if row["record_id"] == "precise-cost")
    assert precise["cost_amount_text"] == "0.123456789012345678901"
    assert precise["cost_amount"] is None
    assert any(row["kind"] == "subagent" and row["resolved"] for row in rows(dataset, "links"))
    assert any(row["kind"] == "parent_subagent" and row["resolved"] for row in rows(dataset, "links"))
    assert any(row["kind"] == "inference" and not row["resolved"] for row in rows(dataset, "links"))
    assert any(row["kind"] == "copied_from" and not row["resolved"] for row in rows(dataset, "links"))


def test_settings_merges_clears_and_never_fills_inference(dataset):
    changes = {row["record_id"]: json.loads(row["effective_json"]) for row in rows(dataset, "settings_changes")}
    assert changes["settings-1"]["modelSettings"]["temperature"] == 0
    assert changes["settings-1"]["sandbox"]["write"] is False
    assert "asks" not in changes["settings-2"]
    assert changes["settings-2"]["modelSettings"] == {"temperature": 0}
    assert changes["settings-2"]["externalSandbox"] == {}
    assert "modelSettings" not in changes["settings-3"]
    assert "sandbox" not in changes["settings-3"]
    assert update_settings({"asks": "always", "mode": "ask"}, {"mode": "ask"})["asks"] == "always"
    assert update_settings({}, {"modelSettings": {}}) == {}
    call = next(row for row in rows(dataset, "inferences") if row["record_id"] == "unknown-cost")
    assert call["settings_json"] is None and call["model_id"] is None


def test_duplicate_snapshot_dedup_and_revision_conflict(tmp_path):
    source = FIXTURES / "parent.jsonl"
    output = tmp_path / "dedup"
    export([source, source], output)
    assert len(rows(output, "sessions")) == 1
    assert rows(output, "diagnostics")[0]["code"] == "duplicate-session-skipped"
    changed = tmp_path / "changed.jsonl"
    changed.write_bytes(source.read_bytes().replace(b"Synthetic table example", b"Changed title"))
    with pytest.raises(ExportError, match="conflicting-session-revisions"):
        export([source, changed], tmp_path / "conflict")
    assert not (tmp_path / "conflict").exists()
    with pytest.raises(ExportError, match="output-exists"):
        export([source], output)


def test_malformed_complete_lines_recover_and_incomplete_tail_is_deferred(tmp_path):
    source = tmp_path / "recovery.jsonl"
    header = (FIXTURES / "parent.jsonl").read_bytes().splitlines(keepends=True)[0]
    source.write_bytes(header + b'{bad json}\n{"type":"gap","id":"gap","reason":"unknown"}\n'
                       + b'{"type":"gap","id":"duplicate-key","reason":"unknown","reason":"deleted"}\n'
                       + b'{"type":"message","id":"bad-utf8","value":"\xff"}\n'
                       + b'{"type":"gap","id":"tail","reason":"unknown"}')
    output = tmp_path / "recovery"
    export([source], output)
    assert [row["record_id"] for row in rows(output, "records")] == ["header", "gap"]
    assert [row["line"] for row in rows(output, "diagnostics")] == [2, 4, 5, 6]
    assert [row["position"] for row in rows(output, "records")] == [1, 3]
    assert rows(output, "diagnostics")[-1]["code"] == "incomplete-tail"


def test_invalid_copy_boundary_withholds_credit(tmp_path):
    source = tmp_path / "boundary.jsonl"
    source.write_bytes((FIXTURES / "child.jsonl").read_bytes().replace(b'"copiedThrough":"inherited-inference"', b'"copiedThrough":"absent"'))
    output = tmp_path / "boundary"
    export([source], output)
    assert not any(row["original"] for row in rows(output, "inferences"))
    assert rows(output, "diagnostics")[0]["code"] == "unresolved-copy-boundary"


def test_duplicate_results_are_never_arbitrarily_chosen(tmp_path):
    source = tmp_path / "results.jsonl"
    original = (FIXTURES / "parent.jsonl").read_bytes()
    source.write_bytes(original + b'{"type":"tool_result","id":"second-result","callId":"edit-1","status":"failed"}\n')
    output = tmp_path / "results"
    export([source], output)
    call = next(row for row in rows(output, "tool_calls") if row["record_id"] == "call")
    assert call["outcome"] == "unknown" and call["pairing"] == "ambiguous"
    assert all(row["paired_call_record_id"] is None for row in rows(output, "tool_results") if row["call_id"] == "edit-1")


def test_effective_empty_string_replaces_json_input(tmp_path):
    source = tmp_path / "empty.jsonl"
    source.write_bytes((FIXTURES / "parent.jsonl").read_bytes().replace(b'"input":null', b'"inputText":""'))
    output = tmp_path / "empty"
    export([source], output)
    call = next(row for row in rows(output, "tool_calls") if row["record_id"] == "call")
    assert call["effective_input_text"] == "" and call["effective_input_json"] is None


def test_cli_errors_never_echo_source_or_native_paths(tmp_path, capsys):
    source = tmp_path / "input.jsonl"
    source.write_text('{"type":"session","id":"secret-looking-text","formatVersion":"999"}\n')
    assert main(["export", str(source), "--output", str(tmp_path / "out")]) == 2
    captured = capsys.readouterr()
    assert captured.err == "unsupported-version\n"
    assert not captured.out


def test_reference_encoding():
    assert encode_component("a:%# \t\x7fb") == "a%3A%25%23%20%09%7Fb"
    assert encode_component("é") == "é"
    assert encode_component("\x80\x9f") == "%C2%80%C2%9F"


@pytest.mark.parametrize("amount", ["0.0000000000000000000000", "0.1000000000000000000000",
                                   "99999999999999999999.999999999999999999"])
def test_exact_portable_decimal_never_rounds_or_loses_zero(amount):
    assert money({"amount": Decimal(amount), "currency": "USD"})["cost_amount"] == Decimal(amount)


@pytest.mark.parametrize("amount", ["0.0000000000000000001", "100000000000000000000"])
def test_decimal_outside_range_is_available_as_exact_text(amount):
    result = money({"amount": Decimal(amount), "currency": "USD"})
    assert result["cost_amount"] is None
    assert Decimal(result["cost_amount_text"]) == Decimal(amount)


def test_one_sided_subagent_link_and_missing_scope_are_preserved(tmp_path):
    output = tmp_path / "parent-only"
    export([FIXTURES / "parent.jsonl"], output)
    links = [row for row in rows(output, "links") if row["kind"] == "subagent"]
    assert links and all(not row["resolved"] for row in links)
    output = tmp_path / "child-only"
    export([FIXTURES / "child.jsonl"], output)
    links = [row for row in rows(output, "links") if row["kind"] == "parent_subagent"]
    assert len(links) == 1 and links[0]["resolved"] is False
    assert rows(output, "sessions")[0]["includes_subagents"] is False
    source = tmp_path / "unknown-scope.jsonl"
    source.write_bytes((FIXTURES / "parent.jsonl").read_bytes().replace(b',"includesSubagents":true', b''))
    output = tmp_path / "unknown-scope"
    export([source], output)
    assert rows(output, "sessions")[0]["includes_subagents"] is None


def test_copied_session_totals_never_become_own_totals(tmp_path):
    source = tmp_path / "copied-totals.jsonl"
    source.write_bytes((FIXTURES / "child.jsonl").read_bytes().replace(
        b'"copiedThrough":"inherited-inference"', b'"copiedThrough":"child-total"'))
    output = tmp_path / "copied-totals"
    export([source], output)
    session = rows(output, "sessions")[0]
    assert session["latest_usage_json"] is None and session["latest_cost_json"] is None


def test_copied_delegations_do_not_make_this_session_a_parent(tmp_path):
    source = tmp_path / "copied-delegation.jsonl"
    raw = (FIXTURES / "parent.jsonl").read_bytes()
    for ident in (b'spawn', b'spawn-result'):
        raw = raw.replace(b'"id":"' + ident + b'",', b'"id":"' + ident
                          + b'","copiedFrom":{"session":"com.example.agent:unavailable"},')
    source.write_bytes(raw)
    output = tmp_path / "copied-delegation"
    export([source], output)
    database = tmp_path / "copied.duckdb"
    load_duckdb(output, database)
    with duckdb.connect(str(database)) as connection:
        query = (HERE.parent / 'queries/subagents.sql').read_text()
        assert connection.execute(query).fetchall() == []


def test_loader_replaces_snapshot_and_quotes_file_paths(tmp_path):
    output = tmp_path / "quote' and space"
    export([FIXTURES / "parent.jsonl"], output)
    database = tmp_path / "table snapshot.duckdb"
    load_duckdb(output, database)
    load_duckdb(output, database)
    with duckdb.connect(str(database)) as connection:
        assert connection.execute('SELECT count(*) FROM sessions').fetchone() == (1,)


def test_loader_rolls_back_if_any_table_is_absent(dataset, tmp_path):
    database = tmp_path / "snapshot.duckdb"
    load_duckdb(dataset, database)
    (dataset / 'messages.parquet').unlink()
    with pytest.raises(duckdb.Error):
        load_duckdb(dataset, database)
    with duckdb.connect(str(database)) as connection:
        assert connection.execute('SELECT count(*) FROM messages').fetchone() == (3,)


def test_fixtures_validate_zero_errors():
    for source in sorted(FIXTURES.glob("*.jsonl")):
        result = subprocess.run(["node", str(ROOT / "tools/validator/bin/asr-validate.js"),
                                 str(source)], capture_output=True, text=True)
        assert result.returncode == 0, "fixture validation failed"


@pytest.mark.parametrize("source", sorted(
    path for directory in (ROOT / "samples", ROOT / "examples")
    for path in directory.rglob("*.jsonl")
    if not path.name.endswith(".annotations.jsonl") and (directory.name == "examples" or "asr" in path.parts)
), ids=lambda path: str(path.relative_to(ROOT)))
def test_repository_samples_and_examples(source, tmp_path):
    output = tmp_path / "tables"
    result = export([source], output)
    assert result["sessions"] == 1
    assert result["tables"]["records"] == len(source.read_bytes().splitlines())
    load_duckdb(output, tmp_path / "sample.duckdb")
