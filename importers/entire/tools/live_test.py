"""Exercise the released Entire CLI with synthetic hooks and no model or account."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile

from asr_entire import REF, import_repository


def run(binary: Path, destination: Path) -> dict:
    root = Path(__file__).resolve().parents[3]
    destination.mkdir(parents=True, mode=0o700, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="asr-entire-live-") as temporary:
        scratch = Path(temporary)
        repo = scratch / "repo"
        repo.mkdir()
        config = scratch / "config"
        config.mkdir(mode=0o700)
        # The release has no update-check opt-out. Seed its documented cache so
        # this run does not make a release-origin request after public commands.
        (config / "version_check.json").write_text(json.dumps({"last_check_time": datetime.now(timezone.utc).isoformat()}))
        env = {key: value for key, value in os.environ.items() if not key.startswith(("GIT_", "ENTIRE_"))}
        env.update(ENTIRE_CONFIG_DIR=str(config), ENTIRE_TELEMETRY_OPTOUT="1", ENTIRE_NO_AUTO_UPDATE="1",
                   ENTIRE_TEST_CLAUDE_PROJECT_DIR=str(scratch / "empty-agent-history"),
                   PATH=str(binary.parent) + os.pathsep + env.get("PATH", ""),
                   GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0",
                   HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9", ALL_PROXY="http://127.0.0.1:9")

        def command(argv, payload=None):
            result = subprocess.run(argv, cwd=repo, env=env, input=json.dumps(payload).encode() if payload is not None else None,
                                    capture_output=True, timeout=60)
            if result.returncode:
                raise RuntimeError("synthetic local CLI step failed with code " + str(result.returncode))
            return result.stdout

        command(["git", "init", "-q", "-b", "main"])
        command(["git", "config", "user.name", "Synthetic Test"])
        command(["git", "config", "user.email", "synthetic@example.invalid"])
        command(["git", "config", "commit.gpgsign", "false"])
        (repo / "example.txt").write_text("before\n")
        command(["git", "add", "."])
        command(["git", "commit", "-qm", "Synthetic baseline"])
        command([str(binary), "enable", "--agent", "claude-code", "--checkpoint-backend", "branch",
                 "--telemetry=false", "--skip-push-sessions", "--no-init-repo", "--absolute-git-hook-path"])
        session = "00000000-0000-4000-8000-000000000001"
        transcript = scratch / "synthetic-session.jsonl"
        at = "2026-10-01T10:00:00Z"
        user = {"type": "user", "uuid": "synthetic-prompt", "sessionId": session, "cwd": str(repo), "timestamp": at,
                "message": {"role": "user", "content": "Change the synthetic example file."}}
        transcript.write_text(json.dumps(user) + "\n")
        payload = {"session_id": session, "transcript_path": str(transcript), "cwd": str(repo), "model": "synthetic-model"}
        command([str(binary), "hooks", "claude-code", "session-start"], {**payload, "hook_event_name": "SessionStart", "source": "startup"})
        command([str(binary), "hooks", "claude-code", "user-prompt-submit"], {**payload, "hook_event_name": "UserPromptSubmit", "prompt": "Change the synthetic example file."})
        assistant = {"type": "assistant", "uuid": "synthetic-assistant", "sessionId": session, "cwd": str(repo), "timestamp": at,
                     "message": {"id": "synthetic-live-response", "role": "assistant", "model": "synthetic-model",
                                 "content": [{"type": "text", "text": "Updated the example."}],
                                 "usage": {"input_tokens": 10, "output_tokens": 3}, "stop_reason": "end_turn"}}
        transcript.write_text(json.dumps(user) + "\n" + json.dumps(assistant) + "\n")
        (repo / "example.txt").write_text("after\n")
        command([str(binary), "hooks", "claude-code", "stop"], {**payload, "hook_event_name": "Stop", "stop_hook_active": False})
        command(["git", "add", "."])
        command(["git", "commit", "-qm", "Synthetic checkpoint"])
        paths = import_repository(repo, destination)
        if len(paths) != 1:
            raise RuntimeError("expected one saved checkpoint session")
        result = command(["node", str(root / "tools/validator/bin/asr-validate.js"), "--json", str(paths[0])])
        validation = json.loads(result)
        records = [json.loads(line) for line in paths[0].read_text().splitlines()]
        if not any(row["type"] == "inference" for row in records):
            raise RuntimeError("the checkpoint transcript was not imported")
        return {"cliVersion": "0.12.2", "scenario": "released CLI, scripted synthetic Claude Code hooks, local Git commit",
                "modelRequests": 0, "accounts": 0, "sessions": len(paths), "records": dict(Counter(row["type"] for row in records)),
                "validation": validation, "branch": REF, "telemetry": False, "pushSessions": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--entire", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.entire.resolve(), args.output_dir.resolve())
    args.summary.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "validation"}))


if __name__ == "__main__":
    main()
