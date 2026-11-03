#!/usr/bin/env python3
"""Commit the public Claude sample and check converted and hook edit citations."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

CORE = Path(__file__).resolve().parents[1]
ROOT = CORE.parents[1]
SAMPLE = ROOT / "samples/claude-code/synthetic-success"
sys.path.insert(0, str(CORE))
from adapters import load
from storage import capture


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def validate(directory):
    result = json.loads(subprocess.check_output([
        "node", str(ROOT / "tools/validator/bin/asr-validate.js"),
        "--json", "--summary", str(directory)], text=True))
    assert result["errors"] == 0, result
    return {key: result[key] for key in ("files", "records", "errors", "warnings", "counts")}


def check(binary):
    with tempfile.TemporaryDirectory(prefix="asr-hook-blame-") as temporary:
        root = Path(temporary)
        repo, hooks, converted = root / "repo", root / "hooks", root / "converted"
        repo.mkdir()

        def git(*args):
            return subprocess.check_output([
                "git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
                "-c", "core.fsmonitor=false", "-C", str(repo), *args],
                env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"},
                stderr=subprocess.DEVNULL, text=True).strip()

        def commit(message):
            git("add", ".")
            git("-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid",
                "commit", "-q", "-m", message)

        git("init", "-q", "-b", "main")
        (repo / "file.txt").write_text("unchanged\nold\n")
        commit("Synthetic baseline")
        native = (SAMPLE / "native.jsonl").read_text().replace("/work/app", str(repo))
        source = root / "native.jsonl"
        source.write_text(native)
        observations = rows(source)
        session = observations[0]["sessionId"]
        calls = {block["id"]: block for row in observations
                 for block in row.get("message", {}).get("content", [])
                 if isinstance(block, dict) and block.get("type") == "tool_use"}
        assert calls["edit-1"]["input"]["old_string"] == "unchanged\nold"
        assert calls["edit-1"]["input"]["new_string"] == "unchanged\nnew"

        def emit(name, **facts):
            capture(str(hooks), session, {"hook_event_name": name, "prompt_id": "turn-1", **facts},
                    "2026-11-01T12:00:00Z", load("claude-code"))

        with patch.dict(os.environ, {"ASR_CONTENT": "full"}):
            emit("SessionStart", source="startup", cwd=str(repo))
            emit("UserPromptSubmit", prompt=observations[0]["message"]["content"])
            for row in observations:
                if "toolUseResult" not in row:
                    continue
                block = row["message"]["content"][0]
                call = calls[block["tool_use_id"]]
                tool, inputs, response = call["name"], call["input"], row["toolUseResult"]
                emit("PreToolUse", tool_use_id=call["id"], tool_name=tool, tool_input=inputs)
                if tool in {"Write", "Edit"}:
                    path = Path(inputs["file_path"])
                    assert path.parent == repo
                    if tool == "Write":
                        path.write_text(inputs["content"])
                    else:
                        assert response["originalFile"] is None
                        before = path.read_text()
                        assert before.count(inputs["old_string"]) == 1
                        path.write_text(before.replace(inputs["old_string"], inputs["new_string"], 1))
                else:
                    assert tool == "Bash" and inputs == {"command": "git diff --check"}
                    git("diff", "--check")
                emit("PostToolUse", tool_use_id=call["id"], tool_name=tool,
                     tool_input=inputs, tool_response=response)
                emit("PostToolBatch", tool_calls=[{"tool_use_id": call["id"],
                     "tool_name": tool, "tool_response": block["content"]}])
        assert (repo / "file.txt").read_text() == "unchanged\nnew\n"
        assert (repo / "created.py").read_text() == "# header\nvalue = 2\n\n# retained write line\nprint(value + 1)\n"
        assert source.read_text() == native
        summary = json.loads(subprocess.check_output([
            binary, "convert", "--agent", "claude-code", str(source), "--out", str(converted)], text=True))
        assert summary["sessions"] == 1 and summary["diagnostics"] == {}, summary
        expected = json.loads(json.dumps(rows(SAMPLE / "asr.jsonl")).replace("/work/app", str(repo)))
        actual = rows(next(converted.glob("*.jsonl")))
        assert [{k: v for k, v in r.items() if k != "id"} for r in actual] == [
            {k: v for k, v in r.items() if k != "id"} for r in expected]
        commit("Synthetic recorded edits")

        results = {}
        for name, directory in (("hooks", hooks), ("converted", converted)):
            records = rows(next(directory.glob("*.jsonl")))
            call_ids = {r["callId"]: r["id"] for r in records if r["type"] == "tool_call"}
            assert all("before" not in r for r in records if r["type"] == "file_change" and "edits" in r)
            counts = {"matched": 0, "unknown": 0}
            for file, line, call in [
                ("file.txt", 1, None), ("file.txt", 2, "edit-1"),
                ("created.py", 1, "shift-1"), ("created.py", 2, "shift-1"),
                ("created.py", 3, "write-1"), ("created.py", 4, "write-1"),
                ("created.py", 5, "tail-1"),
            ]:
                result = json.loads(subprocess.check_output([
                    binary, "blame", file, "--line", str(line), "--repo", str(repo),
                    "--sessions", str(directory)], text=True))
                status = "matched" if call else "unknown"
                assert result["editStatus"] == status, (name, file, line, result)
                counts[status] += 1
                if call:
                    credit, = result["editedBy"]
                    assert credit["session"] == "claude-code:" + session, result
                    assert credit["call"] == "claude-code:" + session + "#" + call_ids[call], result
                    if name == "converted":
                        assert credit["model"]["kind"] == "served", result
                        assert credit["model"]["value"] == "example-served-model", result
                        causing_call = next(r for r in records if r["id"] == call_ids[call])
                        assert credit["model"]["reference"] == "claude-code:" + session + "#" + causing_call["inferenceId"], result
                        assert credit["prompts"][0]["content"][0]["text"] == observations[0]["message"]["content"], result
                else:
                    assert result["editedBy"] == [], result
                assert result["committedBy"] == [] and result["proof"] is False, result
            results[name] = {"checks": counts, "validation": validate(directory)}
        return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(check(str(args.binary.resolve(strict=True))), indent=2))
