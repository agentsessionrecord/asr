from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest

from asr_entire import REF, checked_path, import_repository, native_transcript
from asr_importer_core import Stream

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).parent / "fixtures"


def git(repo, *args):
    return subprocess.run(["git", "-c", "user.name=Synthetic Test", "-c", "user.email=synthetic@example.invalid", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "-C", str(repo), *args], check=True, capture_output=True).stdout


def checkpoint(repo, checkpoint_id, transcript=None, *, session="synthetic-entire-session", pointer=None):
    base = repo / checkpoint_id[:2] / checkpoint_id[2:]
    (base / "0").mkdir(parents=True)
    metadata = json.loads((FIXTURES / "metadata.json").read_text())
    metadata.update(checkpoint_id=checkpoint_id, session_id=session, commit_sha="a" * 40)
    (base / "0/metadata.json").write_text(json.dumps(metadata))
    if transcript is not None:
        (base / "0/full.jsonl").write_bytes(transcript)
    prefix = "/" + checkpoint_id[:2] + "/" + checkpoint_id[2:] + "/0/"
    summary = {"checkpoint_id": checkpoint_id, "sessions": [{"metadata": prefix + "metadata.json", "transcript": pointer or prefix + "full.jsonl"}]}
    (base / "metadata.json").write_text(json.dumps(summary))
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "Synthetic checkpoint")


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q")
    git(path, "symbolic-ref", "HEAD", REF)
    return path


def test_checkpoint_prefixes_merge_one_native_session_without_double_counting(repo, tmp_path):
    full = (FIXTURES / "full.jsonl").read_bytes()
    checkpoint(repo, "ab1234567890", full.splitlines(keepends=True)[0])
    checkpoint(repo, "cd1234567890", full)
    before = git(repo, "rev-parse", "HEAD")
    outputs = import_repository(repo, tmp_path / "out")
    assert len(outputs) == 1
    rows = [json.loads(line) for line in outputs[0].read_text().splitlines()]
    assert sum(row["type"] == "inference" for row in rows) == 1
    inference = next(row for row in rows if row["type"] == "inference")
    assert inference["usage"] == {"inputTokens": 15, "cacheReadTokens": 3, "cacheWriteTokens": 2, "outputTokens": 0}
    assert not any(row["type"] in ("vcs", "file_change") for row in rows)
    assert rows[0]["sessionId"] == "synthetic-entire-session"
    assert "startedAt" not in rows[0]
    assert git(repo, "rev-parse", "HEAD") == before
    with pytest.raises(ValueError):
        import_repository(repo, tmp_path / "out")


def test_multiple_sessions_missing_transcript_and_pointer_escape(repo, tmp_path):
    checkpoint(repo, "ab1234567890", None)
    checkpoint(repo, "cd1234567890", (FIXTURES / "full.jsonl").read_bytes(), session="another-native-session")
    outputs = import_repository(repo, tmp_path / "out")
    assert len(outputs) == 2
    assert any(any(json.loads(line).get("type") == "gap" for line in out.read_text().splitlines()) for out in outputs)
    with pytest.raises(ValueError):
        checked_path("/ab/1234567890/../outside", "ab/1234567890")
    checkpoint(repo, "ef1234567890", None, pointer="/outside/private.jsonl")
    with pytest.raises(ValueError):
        import_repository(repo, tmp_path / "rejected")
    assert not (tmp_path / "rejected").exists()


def test_corrupt_and_incomplete_native_lines_become_gaps(tmp_path):
    stream = Stream("claude-code", "synthetic", "test")
    native_transcript(stream, b'{"bad":\n{}', "claude-code")
    stream.write(tmp_path / "corrupt.jsonl")
    assert all(row["type"] == "gap" for row in stream.records)


def test_documented_raw_mapping_sample(tmp_path):
    stream = Stream("claude-code", "synthetic-entire-session", "entire-checkpoints-v1")
    native_transcript(stream, (FIXTURES / "full.jsonl").read_bytes(), "claude-code")
    output = tmp_path / "entire.jsonl"
    stream.write(output)
    assert output.read_bytes() == (FIXTURES / "full.expected.asr.jsonl").read_bytes()


@pytest.mark.parametrize("agent", ["claude-code", "codex"])
def test_checked_in_native_samples(agent, tmp_path):
    data = (ROOT / "samples" / agent / "native/session.jsonl").read_bytes()
    # The checked-in samples contain only synthetic work.
    first = json.loads(data.splitlines()[0])
    session = first.get("sessionId", first.get("payload", {}).get("id"))
    stream = Stream(agent, session, "entire-checkpoints-v1")
    native_transcript(stream, data, agent)
    stream.write(tmp_path / f"{agent}.jsonl")
    assert any(row["type"] == "message" for row in stream.records)
    assert any(row["type"] == "tool_call" for row in stream.records)
    assert any(row["type"] == "inference" for row in stream.records)


def test_raw_transcript_chunks(repo, tmp_path):
    full = (FIXTURES / "full.jsonl").read_bytes()
    first, rest = full.split(b"\n", 1)
    checkpoint(repo, "ab1234567890", first + b"\n")
    chunk = repo / "ab/1234567890/0/full.jsonl.001"
    chunk.write_bytes(rest)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "Synthetic chunk")
    outputs = import_repository(repo, tmp_path / "out")
    assert any(json.loads(line)["type"] == "inference" for line in outputs[0].read_text().splitlines())


def test_divergent_checkpoints_keep_branch_work_and_report_conflicts(repo, tmp_path):
    full = (FIXTURES / "full.jsonl").read_bytes()
    checkpoint(repo, "ab1234567890", full)
    rows = [json.loads(line) for line in full.splitlines()]
    rows[0]["message"]["content"] = "A revised prompt."
    rows.append({"type": "user", "uuid": "synthetic-branch", "timestamp": "2026-10-01T10:01:00Z", "message": {"role": "user", "content": "A retained branch."}})
    checkpoint(repo, "cd1234567890", ''.join(json.dumps(row) + '\n' for row in rows).encode())
    output = import_repository(repo, tmp_path / "out")[0]
    records = [json.loads(line) for line in output.read_text().splitlines()]
    assert sum(row["type"] == "inference" for row in records) == 1
    assert any(row.get("id") == "synthetic-branch" for row in records)
    assert "checkpoint_order" in records[0]["missing"]
    assert sum(row["type"] == "gap" for row in records) == 2


def test_cli_reads_the_checkpoint_branch(repo, tmp_path):
    import sys

    checkpoint(repo, "ab1234567890", (FIXTURES / "full.jsonl").read_bytes())
    output = tmp_path / "cli-output"
    result = subprocess.run([sys.executable, "-m", "asr_entire", str(repo), "--output-dir", str(output)], capture_output=True, text=True)
    assert result.returncode == 0 and "1 session" in result.stdout
    result = subprocess.run(["node", str(ROOT / "tools/validator/bin/asr-validate.js"), str(output)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_native_snapshots_complete_after_intervening_records(tmp_path):
    rows = [json.loads(line) for line in (FIXTURES / "full.jsonl").read_text().splitlines()]
    initial = deepcopy(rows[1])
    initial["message"]["usage"]["output_tokens"] = 1
    final = deepcopy(rows[1])
    final["message"]["usage"]["output_tokens"] = 4
    notice = {"type": "user", "uuid": "synthetic-notice", "message": {"role": "user", "content": "Intervening notice."}}
    data = ''.join(json.dumps(row) + '\n' for row in [initial, notice, final]).encode()
    stream = Stream("claude-code", "synthetic", "test")
    native_transcript(stream, data, "claude-code")
    stream.write(tmp_path / "completed.jsonl")
    assert stream.records[0]["id"] == "synthetic-notice"
    assert sum(row["type"] == "inference" for row in stream.records) == 1
    assert stream.records[-1]["usage"]["outputTokens"] == 4
