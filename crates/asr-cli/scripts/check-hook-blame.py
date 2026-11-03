#!/usr/bin/env python3
"""Run the shared synthetic hook check with explicit edit and commit times."""
import argparse
import datetime
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
CORE = ROOT / "plugins/hooks-core"
sys.path.insert(0, str(CORE))
module_spec = importlib.util.spec_from_file_location("hook_blame_check", CORE / "tests/check_blame.py")
hook_check = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(hook_check)


class ReceiptClock(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 1, 12, 0, tzinfo=datetime.timezone.utc).astimezone(tz)


def check(binary):
    """Check actual results, allowing missing context to remain unknown."""
    binary = str(binary.resolve(strict=True))
    with tempfile.TemporaryDirectory(prefix="asr-timed-hook-check-") as scratch:
        scratch = Path(scratch)
        repo, hooks, converted = scratch / "repo", scratch / "hooks", scratch / "converted"
        repo.mkdir()

        def command(args, at="2026-11-01T12:01:00Z"):
            result = subprocess.run(args, cwd=repo, env={**os.environ,
                "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_AUTHOR_DATE": at, "GIT_COMMITTER_DATE": at,
                "GIT_AUTHOR_NAME": "Synthetic", "GIT_COMMITTER_NAME": "Synthetic",
                "GIT_AUTHOR_EMAIL": "test@example.invalid", "GIT_COMMITTER_EMAIL": "test@example.invalid"},
                capture_output=True, text=True, check=True, timeout=30)
            return result.stdout

        def git(*args, at="2026-11-01T12:01:00Z"):
            return command(["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", *args], at)

        git("init", "-qb", "main")
        (repo / "file.txt").write_text("unchanged\nold\n")
        git("add", ".")
        git("commit", "-qm", "Synthetic baseline", at="2026-11-01T11:59:00Z")
        native = hook_check.rows(hook_check.SAMPLE / "native.jsonl")
        native = json.loads(json.dumps(native).replace("/work/app", str(repo)))
        for record in native:
            record["timestamp"] = "2026-11-01T12:00:00Z"
        source = scratch / "native.jsonl"
        source.write_text("".join(json.dumps(r) + "\n" for r in native))
        session = native[0]["sessionId"]
        calls = {block["id"]: block for row in native for block in row.get("message", {}).get("content", [])
                 if isinstance(block, dict) and block.get("type") == "tool_use"}

        def emit(event, **facts):
            hook_check.capture(str(hooks), session, {"hook_event_name": event, "prompt_id": "turn-1", **facts},
                               "2026-11-01T12:00:00Z", hook_check.load("claude-code"))

        with patch.dict(os.environ, {"ASR_CONTENT": "full"}), patch("storage.datetime.datetime", ReceiptClock):
            emit("SessionStart", source="startup", cwd=str(repo))
            emit("UserPromptSubmit", prompt=native[0]["message"]["content"])
            for row in native:
                if "toolUseResult" not in row:
                    continue
                call = calls[row["message"]["content"][0]["tool_use_id"]]
                name, inputs = call["name"], call["input"]
                emit("PreToolUse", tool_use_id=call["id"], tool_name=name, tool_input=inputs)
                if name in {"Edit", "Write"}:
                    file = Path(inputs["file_path"])
                    assert file.parent == repo
                    if name == "Write":
                        file.write_text(inputs["content"])
                    else:
                        before = file.read_text()
                        assert before.count(inputs["old_string"]) == 1
                        file.write_text(before.replace(inputs["old_string"], inputs["new_string"], 1))
                else:
                    git("diff", "--check")
                emit("PostToolUse", tool_use_id=call["id"], tool_name=name,
                     tool_input=inputs, tool_response=row["toolUseResult"])
                emit("PostToolBatch", tool_calls=[{"tool_use_id": call["id"], "tool_name": name,
                     "tool_response": row["message"]["content"][0]["content"]}])
        summary = json.loads(command([binary, "convert", "--agent", "claude-code", str(source), "--out", str(converted)]))
        assert summary["sessions"] == 1
        git("add", ".")
        git("commit", "-qm", "Synthetic recorded edits")
        results = {}
        for name, directory in [("hooks", hooks), ("converted", converted)]:
            counts = {"correct": 0, "unknown": 0, "wrong": 0}
            records = hook_check.rows(next(directory.glob("*.jsonl")))
            call_ids = {r["callId"]: r["id"] for r in records if r["type"] == "tool_call"}
            for file, line, call in [("file.txt", 1, None), ("file.txt", 2, "edit-1"),
                                     ("created.py", 1, "shift-1"), ("created.py", 2, "shift-1"),
                                     ("created.py", 3, "write-1"), ("created.py", 4, "write-1"),
                                     ("created.py", 5, "tail-1")]:
                result = json.loads(command([binary, "blame", file, "--line", str(line), "--repo", str(repo),
                                             "--sessions", str(directory)]))
                if result["editStatus"] == "unknown":
                    counts["unknown"] += 1
                else:
                    assert call and result["editStatus"] == "matched", result
                    credit, = result["editedBy"]
                    assert credit["session"] == "claude-code:" + session
                    assert credit["call"] == "claude-code:" + session + "#" + call_ids[call]
                    counts["correct"] += 1
                assert result["committedBy"] == [] and result["proof"] is False
            results[name] = {"checks": counts, "validation": hook_check.validate(directory)}
        return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(check(args.binary), indent=2))
