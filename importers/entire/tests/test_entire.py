from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from asr_entire import (BRANCH, Mapper, checked_path, checkpoint_from_ref, discover, import_repository, map_lines,
                        native_transcript, new_stream)
from asr_entire.normalized import parse
from asr_importer_core import Stream

from entire_store import FIXTURES, build, fixture_store, git, init, jsonl, load_transcripts

ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = ROOT / "tools/validator/bin/asr-validate.js"
CLAUDE = "01KA2SYNTHETC0000000000CA1"
SESSIONS = {"claude-code": "synthetic-claude-session", "codex": "synthetic-codex-session", "pi": "synthetic-pi-session",
            "opencode": "synthetic-opencode-session", "org.agentsessionrecord.entire-unknown": "synthetic-external-session"}


def records(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def meta(record):
    return record.get("_meta", {}).get("org.agentsessionrecord.importers", {})


def by_agent(outputs):
    return {rows[0]["agent"]["name"]: rows for rows in map(records, outputs)}


@pytest.fixture
def store(tmp_path):
    repo = tmp_path / "repo"
    fixture_store(repo)
    return repo


def metadata(cid, session, agent="Claude Code", start=0, compact=0, created="2026-10-01T10:00:00Z"):
    value = {"cli_version": "0.13.2", "checkpoint_id": cid, "session_id": session, "strategy": "manual-commit",
             "created_at": created, "files_touched": [], "agent": agent, "model": ""}
    if start:
        value["checkpoint_transcript_start"] = start
    if compact is not None:
        value["compact_transcript_start"] = compact
    return value


def test_both_backends_three_agents_and_one_session_per_file(store, tmp_path):
    refs_before = git(store, "for-each-ref")
    outputs = import_repository(store, tmp_path / "out")
    sessions = by_agent(outputs)
    assert {name: rows[0]["sessionId"] for name, rows in sessions.items()} == SESSIONS
    backends = {name: {c["backend"] for c in meta(rows[0])["checkpoints"]} for name, rows in sessions.items()}
    assert backends["claude-code"] == {"git-refs"} and backends["codex"] == {"git-branch"}
    for rows in sessions.values():
        assert rows[0]["producer"] == {"name": "asr-import-entire", "version": "0.2.0", "method": "converter",
                                       "source": "entire-transcript-v1"}
        prompts = [part["text"] for row in rows if row["type"] == "message" and row["role"] == "user" for part in row["content"]
                   if part["type"] == "text"]
        # Every checkpoint repeats earlier lines. Each prompt appears once.
        assert len(prompts) == len(set(prompts))
    assert git(store, "for-each-ref") == refs_before
    assert git(store, "status", "--porcelain") == ""


def test_compact_transcript_start_merges_checkpoints_without_loss_or_double_counting(store, tmp_path):
    rows = by_agent(import_repository(store, tmp_path / "out"))["claude-code"]
    assert [c["checkpoint"] for c in meta(rows[0])["checkpoints"]] == [CLAUDE, "01KA2SYNTHETC0000000000CB2",
                                                                       "01KA2SYNTHETC0000000000CC3"]
    inferences = [row for row in rows if row["type"] == "inference"]
    assert [row["id"] for row in inferences] == ["msg_synthetic_a", "msg_synthetic_b", "msg_synthetic_c", "msg_synthetic_d"]
    # The straddling message keeps its final usage, not the earlier partial one.
    assert inferences[0]["usage"] == {"inputTokens": 16, "cacheReadTokens": 4, "cacheWriteTokens": 2, "outputTokens": 9}
    assert sum(row["usage"]["outputTokens"] for row in inferences) == 9 + 4 + 6 + 7
    # The Edit result arrived after its checkpoint. A later view holds it.
    results = {row["callId"]: row for row in rows if row["type"] == "tool_result"}
    assert results["toolu_synthetic_edit"]["content"] == [{"type": "text", "text": "The file was updated."}]
    assert results["toolu_synthetic_check"]["status"] == "failed"
    calls = [row for row in rows if row["type"] == "tool_call"]
    assert [row["callId"] for row in calls] == ["toolu_synthetic_read", "toolu_synthetic_edit", "toolu_synthetic_check"]
    assert all(row["inferenceId"] for row in calls)
    # Each record names the checkpoint whose slice first held it.
    first = {row["callId"]: meta(row)["checkpoint"] for row in calls}
    assert first == {"toolu_synthetic_read": CLAUDE, "toolu_synthetic_edit": "01KA2SYNTHETC0000000000CB2",
                     "toolu_synthetic_check": "01KA2SYNTHETC0000000000CC3"}
    assert "usage" not in rows[0]["missing"] and "model" not in rows[0]["missing"]
    assert {"reasoning", "assets", "content", "message_origin", "checkpoint_history"} <= set(rows[0]["missing"])


def test_divergent_checkpoint_views_keep_earlier_content_after_a_gap(store, tmp_path):
    rows = by_agent(import_repository(store, tmp_path / "out"))["pi"]
    gap = next(index for index, row in enumerate(rows) if row["type"] == "gap")
    assert "checkpoint_order" in rows[0]["missing"]
    kept = [row for row in rows[gap:] if row["type"] == "message"]
    assert kept[0]["content"][0]["text"] == "An abandoned branch reply."
    assert sum(row["type"] == "inference" for row in rows) == 4


def test_migrated_copy_prefers_the_checkpoint_ref(store, tmp_path):
    rows = by_agent(import_repository(store, tmp_path / "out"))["opencode"]
    header = meta(rows[0])
    assert [c["backend"] for c in header["checkpoints"]] == ["git-refs"]
    assert header["shadowedCopies"][0]["backend"] == "git-branch"
    assert rows[-1]["content"][0]["text"] == "There are two files."
    # OpenCode lines count tokens per message, not per model call.
    assert not any(row["type"] == "inference" for row in rows)
    assert {"usage", "model"} <= set(rows[0]["missing"])


def test_external_agent_in_a_multi_session_checkpoint(store, tmp_path):
    rows = by_agent(import_repository(store, tmp_path / "out"))["org.agentsessionrecord.entire-unknown"]
    assert meta(rows[0])["agent"] == "Acme Agent"
    assert meta(rows[0])["checkpoints"][0]["session"] == 1
    assert [row["type"] for row in rows[1:]] == ["message", "message"]


@pytest.mark.parametrize("agent", ["claude-code", "codex", "pi", "opencode"])
def test_documented_normalized_mapping(agent, tmp_path):
    source = FIXTURES / "normalized" / f"{agent}.transcript.jsonl"
    stream = new_stream(agent, f"synthetic-{agent}-session", "entire-transcript-v1")
    map_lines(stream, agent, [(raw, line, None) for raw, line in parse(source.read_bytes())])
    output = tmp_path / f"{agent}.jsonl"
    stream.write(output)
    assert output.read_bytes() == (FIXTURES / "normalized" / f"{agent}.expected.asr.jsonl").read_bytes()


def test_codex_and_pi_usage_rules():
    transcripts = load_transcripts()
    stream = Stream("codex", "synthetic", "test")
    mapper = Mapper(stream, "codex")
    for line in transcripts["codex"]:
        mapper.line(b"", line, {})
    inferences = [row for row in stream.records if row["type"] == "inference"]
    # Codex fresh input excludes cached input. A line without usage is no call.
    assert [row["usage"]["inputTokens"] for row in inferences] == [500, 800, 820]
    assert inferences[0]["model"] == {"requested": "synthetic-codex-model"}
    old = dict(transcripts["claude-code"][1], cli_version="0.11.6")
    stream = Stream("claude-code", "synthetic", "test")
    Mapper(stream, "claude-code").line(b"", old, {})
    # Older Claude Code lines hold fresh input only, so the total is unknown.
    assert next(row for row in stream.records if row["type"] == "inference")["usage"] == {"outputTokens": 9}


def test_corrupt_and_incomplete_normalized_lines_become_gaps(tmp_path):
    stream = Stream("pi", "synthetic", "test")
    mapper = Mapper(stream, "pi")
    for raw, line in parse(b'{"bad":\n{"v":2,"type":"user","content":[]}\n{"v":1,"type":"user","content":[{"text":"cut'):
        mapper.line(raw, line, {})
    stream.write(tmp_path / "corrupt.jsonl")
    assert [row["type"] for row in stream.records] == ["gap", "gap", "gap"]


def test_legacy_delta_checkpoints_concatenate(tmp_path):
    repo = init(tmp_path / "repo")
    lines = load_transcripts()["claude-code"]
    build(repo, {"checkpoints": [
        {"backend": "git-branch", "id": "aa0000000001", "sessions": [
            {"metadata": metadata("aa0000000001", "legacy", compact=None), "lines": lines[:4]}]},
        {"backend": "git-branch", "id": "aa0000000002", "sessions": [
            {"metadata": metadata("aa0000000002", "legacy", start=5, compact=None), "lines": lines[4:]}]}]})
    rows = records(import_repository(repo, tmp_path / "out")[0])
    assert "checkpoint_deltas" in rows[0]["missing"]
    assert sum(row["type"] == "inference" for row in rows) == 4


def test_auto_reads_full_jsonl_when_the_latest_checkpoint_has_no_normalized_transcript(tmp_path):
    repo = init(tmp_path / "repo")
    full = (FIXTURES / "full.jsonl").read_bytes()
    build(repo, {"checkpoints": [{"backend": "git-refs", "id": CLAUDE, "sessions": [
        {"metadata": metadata(CLAUDE, "synthetic-entire-session"), "full": full, "compact": False}]}]})
    rows = records(import_repository(repo, tmp_path / "auto")[0])
    assert rows[0]["producer"]["source"] == "entire-full-jsonl"
    assert next(row for row in rows if row["type"] == "inference")["usage"]["inputTokens"] == 15
    rows = records(import_repository(repo, tmp_path / "normalized", transcript="normalized")[0])
    assert [row["type"] for row in rows[1:]] == ["gap"]


def test_full_transcript_choice_reads_raw_snapshots_for_claude_code(store, tmp_path):
    repo = init(tmp_path / "raw")
    full = (FIXTURES / "full.jsonl").read_bytes()
    first, rest = full.split(b"\n", 1)
    build(repo, {"checkpoints": [
        {"backend": "git-branch", "id": "ab1234567890", "sessions": [
            {"metadata": metadata("ab1234567890", "synthetic-entire-session"), "full": first + b"\n", "lines": []}]},
        {"backend": "git-branch", "id": "cd1234567890", "sessions": [
            {"metadata": metadata("cd1234567890", "synthetic-entire-session", start=1, compact=1), "full": full, "lines": []}]}]})
    rows = records(import_repository(repo, tmp_path / "out", transcript="full")[0])
    assert rows[0]["producer"]["source"] == "entire-full-jsonl"
    assert sum(row["type"] == "inference" for row in rows) == 1


def test_raw_transcript_chunks(tmp_path):
    repo = init(tmp_path / "repo")
    full = (FIXTURES / "full.jsonl").read_bytes()
    first, rest = full.split(b"\n", 1)
    spec = {"checkpoints": [{"backend": "git-branch", "id": "ab1234567890", "sessions": [
        {"metadata": metadata("ab1234567890", "synthetic-entire-session"), "full": first + b"\n", "compact": False}]}]}
    build(repo, spec)
    tree = {path: git(repo, "rev-parse", f"{BRANCH}:{path}") for path in git(repo, "ls-tree", "-r", "--name-only", BRANCH).split()}
    tree["ab/1234567890/0/full.jsonl.001"] = git(repo, "hash-object", "-w", "--stdin", data=rest)
    index = {"GIT_INDEX_FILE": str(repo / ".git" / "chunk-index")}
    for path, oid in tree.items():
        git(repo, "update-index", "--add", "--cacheinfo", f"100644,{oid},{path}", env=index)
    commit = git(repo, "commit-tree", git(repo, "write-tree", env=index), "-p", BRANCH, "-m", "Synthetic chunk")
    git(repo, "update-ref", BRANCH, commit)
    rows = records(import_repository(repo, tmp_path / "out")[0])
    assert any(row["type"] == "inference" for row in rows)


def test_pointer_escape_and_ref_names(tmp_path):
    with pytest.raises(ValueError):
        checked_path("/ab/1234567890/../outside", "ab/1234567890")
    assert checked_path("/0/metadata.json", "") == "0/metadata.json"
    assert checked_path("/ab/1234567890/0/full.jsonl", "", strip="ab/1234567890") == "0/full.jsonl"
    with pytest.raises(ValueError):
        checked_path("/../metadata.json", "")
    assert checkpoint_from_ref("refs/entire/checkpoints/A1/" + CLAUDE) == CLAUDE
    assert checkpoint_from_ref("refs/entire/checkpoints/ZZ/" + CLAUDE) is None
    assert checkpoint_from_ref("refs/entire/checkpoints/90/ab1234567890/extra") is None
    repo = init(tmp_path / "repo")
    build(repo, {"checkpoints": [{"backend": "git-refs", "id": CLAUDE, "summary": {"sessions": [{"metadata": "/../outside.json"}]},
                                  "sessions": [{"metadata": metadata(CLAUDE, "escape"), "lines": []}]}]})
    with pytest.raises(ValueError):
        import_repository(repo, tmp_path / "rejected")
    assert not (tmp_path / "rejected").exists()


def test_existing_outputs_are_never_overwritten(store, tmp_path):
    import_repository(store, tmp_path / "out")
    with pytest.raises(ValueError):
        import_repository(store, tmp_path / "out")


def test_importer_command_reads_both_backends(store, tmp_path):
    output = tmp_path / "cli-output"
    result = subprocess.run([sys.executable, "-m", "asr_entire", str(store), "--output-dir", str(output)],
                            capture_output=True, text=True)
    assert result.returncode == 0 and "5 session" in result.stdout
    result = subprocess.run(["node", str(VALIDATOR), str(output)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_documented_raw_mapping_sample(tmp_path):
    stream = Stream("claude-code", "synthetic-entire-session", "entire-checkpoints-v1")
    native_transcript(stream, (FIXTURES / "full.jsonl").read_bytes(), "claude-code")
    output = tmp_path / "entire.jsonl"
    stream.write(output)
    assert output.read_bytes() == (FIXTURES / "full.expected.asr.jsonl").read_bytes()


def test_corrupt_and_incomplete_native_lines_become_gaps(tmp_path):
    stream = Stream("claude-code", "synthetic", "test")
    native_transcript(stream, b'{"bad":\n{}', "claude-code")
    stream.write(tmp_path / "corrupt.jsonl")
    assert all(row["type"] == "gap" for row in stream.records)


@pytest.mark.parametrize("agent", ["claude-code", "codex"])
def test_checked_in_native_samples(agent, tmp_path):
    data = (ROOT / "samples" / agent / "native/session.jsonl").read_bytes()
    first = json.loads(data.splitlines()[0])
    session = first.get("sessionId", first.get("payload", {}).get("id"))
    stream = Stream(agent, session, "entire-checkpoints-v1")
    native_transcript(stream, data, agent)
    stream.write(tmp_path / f"{agent}.jsonl")
    assert any(row["type"] == "message" for row in stream.records)
    assert any(row["type"] == "tool_call" for row in stream.records)
    assert any(row["type"] == "inference" for row in stream.records)


def test_native_snapshots_complete_after_intervening_records(tmp_path):
    rows = [json.loads(line) for line in (FIXTURES / "full.jsonl").read_text().splitlines()]
    initial = deepcopy(rows[1])
    initial["message"]["usage"]["output_tokens"] = 1
    final = deepcopy(rows[1])
    final["message"]["usage"]["output_tokens"] = 4
    notice = {"type": "user", "uuid": "synthetic-notice", "message": {"role": "user", "content": "Intervening notice."}}
    stream = Stream("claude-code", "synthetic", "test")
    native_transcript(stream, jsonl([initial, notice, final]), "claude-code")
    stream.write(tmp_path / "completed.jsonl")
    assert stream.records[0]["id"] == "synthetic-notice"
    assert sum(row["type"] == "inference" for row in stream.records) == 1
    assert stream.records[-1]["usage"]["outputTokens"] == 4


def test_discover_groups_copies_by_session(store):
    sessions = {session.session_id: session for session in discover(store)}
    assert sessions["synthetic-claude-session"].checkpoints == [CLAUDE, "01KA2SYNTHETC0000000000CB2", "01KA2SYNTHETC0000000000CC3"]
    assert sessions["synthetic-codex-session"].checkpoints == ["c0de0000a001", "c0de0000a002"]
