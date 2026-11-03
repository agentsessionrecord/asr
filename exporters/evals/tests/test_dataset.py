from copy import deepcopy

from asr_evals.dataset import final_diff, rows, task_prompt
from asr_evals.reader import Session, read_annotations, read_session
from conftest import FIXTURES, ROOT


def test_task_prompt_respects_part_authorship(session):
    prompt = task_prompt(session)
    assert prompt["text"] == "Handle empty input.\nRun tests."
    assert prompt["reference"].endswith("#prompt%20%231")


def test_dataset_contains_observed_diff_start_and_test_evidence(session):
    annotations, _ = read_annotations([FIXTURES / "tests.annotations.jsonl"])
    row = rows([session], annotations, include_content=True)[0]
    assert row["input"]["starting_commit"] == "a" * 40
    assert "-    return text.split(',')\n" in row["expected"]["final_diff"]
    assert "+    return text.split(',') if text else []\n" in row["expected"]["final_diff"]
    tests = row["expected"]["test_results"]
    assert tests[0]["tool_status"] == "completed" and tests[0]["test_status"] is None
    assert tests[0]["exec"]["exitCode"] == 0
    assert [t["test_status"] for t in tests[1:]] == ["passed", "failed"]


def test_no_content_default_and_compaction_is_not_prompt(session):
    row = rows([session])[0]
    assert row["input"]["task_prompt"] is None
    assert row["expected"]["final_diff"] is None
    records = deepcopy(session.records)
    records[0]["origin"] = "compaction"
    other = Session(session.header, records, "synthetic")
    assert task_prompt(other) is None


def test_snapshot_chain_net_diff_and_discontinuity(session):
    first = session.by_id["change-1"]
    second = dict(deepcopy(first), id="change-2", before=first["after"], after=first["before"])
    other = Session(session.header, [first, second], "synthetic")
    assert final_diff(other) == ("", "observed_snapshot_chain")
    second["before"] = {"text": "unobserved edit\n"}
    assert final_diff(Session(session.header, [first, second], "synthetic"))[0] is None


def test_no_newline_and_added_file_diff(session):
    change = {"type": "file_change", "id": "add", "path": "new.txt", "op": "add", "status": "applied", "after": {"text": "new text"}}
    diff, _ = final_diff(Session(session.header, [change], "synthetic"))
    assert diff.startswith("--- /dev/null\n+++ b/new.txt\n")
    assert diff.endswith("\\ No newline at end of file\n")


def test_snippets_do_not_claim_complete_final_diff():
    session = read_session(ROOT / "examples/coding-session.jsonl")
    diff, reason = final_diff(session)
    assert diff is None and reason == "full_snapshots_unavailable"
    assert rows([session], include_content=True)[0]["expected"]["test_results"][0]["exec"]["exitCode"] == 0
