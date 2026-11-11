"""Exercise the released Entire CLI with synthetic hooks and no model or account.

For each checkpoint backend, a throwaway repository records one scripted Claude
Code session across two commits. The importer reads the checkpoints, then
`entire asr export` runs the external command through Entire itself.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile

from asr_entire import import_repository

ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = ROOT / "tools/validator/bin/asr-validate.js"
SESSION = "00000000-0000-4000-8000-000000000001"


def scripted_session(repo: Path, scratch: Path, command) -> None:
    transcript = scratch / "synthetic-session.jsonl"

    def entry(kind, uuid, at, message, **extra):
        return {"type": kind, "uuid": uuid, "sessionId": SESSION, "cwd": str(repo), "timestamp": at, "message": message, **extra}

    first = entry("user", "synthetic-prompt-1", "2026-10-01T10:00:00Z",
                  {"role": "user", "content": "Change the synthetic example file."}, promptId="synthetic-prompt-1")
    call = entry("assistant", "synthetic-call", "2026-10-01T10:00:01Z",
                 {"id": "synthetic-live-response-1", "role": "assistant", "model": "synthetic-model",
                  "content": [{"type": "tool_use", "id": "toolu_synthetic_write", "name": "Write",
                               "input": {"file_path": str(repo / "example.txt"), "content": "after\n"}}],
                  "usage": {"input_tokens": 10, "cache_read_input_tokens": 4, "cache_creation_input_tokens": 2,
                            "output_tokens": 5}, "stop_reason": "tool_use"})
    result = entry("user", "synthetic-result", "2026-10-01T10:00:02Z",
                   {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_synthetic_write",
                                                 "content": "File written"}]})
    done = entry("assistant", "synthetic-done", "2026-10-01T10:00:03Z",
                 {"id": "synthetic-live-response-2", "role": "assistant", "model": "synthetic-model",
                  "content": [{"type": "text", "text": "Updated the example."}],
                  "usage": {"input_tokens": 20, "output_tokens": 3}, "stop_reason": "end_turn"})
    second = entry("user", "synthetic-prompt-2", "2026-10-01T10:01:00Z",
                   {"role": "user", "content": "Add a second line."}, promptId="synthetic-prompt-2")
    added = entry("assistant", "synthetic-added", "2026-10-01T10:01:01Z",
                  {"id": "synthetic-live-response-3", "role": "assistant", "model": "synthetic-model",
                   "content": [{"type": "text", "text": "Added it."}],
                   "usage": {"input_tokens": 30, "output_tokens": 4}, "stop_reason": "end_turn"})
    payload = {"session_id": SESSION, "transcript_path": str(transcript), "cwd": str(repo), "model": "synthetic-model"}

    def hook(name, event, **fields):
        command(["entire", "hooks", "claude-code", name], {**payload, "hook_event_name": event, **fields})

    def write(*rows):
        transcript.write_text("".join(json.dumps(row) + "\n" for row in rows))

    write(first)
    hook("session-start", "SessionStart", source="startup")
    hook("user-prompt-submit", "UserPromptSubmit", prompt="Change the synthetic example file.")
    write(first, call, result, done)
    (repo / "example.txt").write_text("after\n")
    hook("stop", "Stop", stop_hook_active=False)
    command(["git", "add", "."])
    command(["git", "commit", "-qm", "Synthetic checkpoint one"])
    hook("user-prompt-submit", "UserPromptSubmit", prompt="Add a second line.")
    write(first, call, result, done, second, added)
    (repo / "example.txt").write_text("after\nsecond\n")
    hook("stop", "Stop", stop_hook_active=False)
    command(["git", "add", "."])
    command(["git", "commit", "-qm", "Synthetic checkpoint two"])


def validate(path: Path) -> dict:
    result = subprocess.run(["node", str(VALIDATOR), "--json", str(path)], capture_output=True, text=True, check=False)
    return json.loads(result.stdout)


def run(entire: Path, plugin: Path, destination: Path, backend: str) -> dict:
    destination.mkdir(parents=True, mode=0o700, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="asr-entire-live-") as temporary:
        scratch = Path(temporary)
        repo = scratch / "repo"
        repo.mkdir()
        home = scratch / "home"
        config = scratch / "entire-config"
        for directory in (home, config, scratch / "xdg-config", scratch / "xdg-data", scratch / "xdg-cache"):
            directory.mkdir(mode=0o700)
        # The release has no update-check opt-out. Seed its documented cache so
        # this run does not make a release-origin request after public commands.
        (config / "version_check.json").write_text(json.dumps({"last_check_time": datetime.now(timezone.utc).isoformat()}))
        # Agent and provider settings from the calling session stay out of the run.
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("GIT_", "ENTIRE_", "XDG_", "CLAUDE", "ANTHROPIC_", "OPENAI_", "CODEX_"))}
        env.update(HOME=str(home), XDG_CONFIG_HOME=str(scratch / "xdg-config"), XDG_DATA_HOME=str(scratch / "xdg-data"),
                   XDG_CACHE_HOME=str(scratch / "xdg-cache"), ENTIRE_CONFIG_DIR=str(config),
                   ENTIRE_TELEMETRY_OPTOUT="1", ENTIRE_NO_AUTO_UPDATE="1",
                   ENTIRE_TEST_CLAUDE_PROJECT_DIR=str(scratch / "empty-agent-history"),
                   PATH=str(entire.parent) + os.pathsep + env.get("PATH", ""),
                   GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0",
                   HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9", ALL_PROXY="http://127.0.0.1:9")

        def command(argv, payload=None):
            result = subprocess.run(argv, cwd=repo, env=env, input=json.dumps(payload).encode() if payload is not None else None,
                                    capture_output=True, timeout=120)
            if result.returncode:
                raise RuntimeError(f"synthetic local step {argv[:3]} failed with code {result.returncode}")
            return result.stdout

        command(["git", "init", "-q", "-b", "main"])
        command(["git", "config", "user.name", "Synthetic Test"])
        command(["git", "config", "user.email", "synthetic@example.invalid"])
        command(["git", "config", "commit.gpgsign", "false"])
        (repo / "example.txt").write_text("before\n")
        command(["git", "add", "."])
        command(["git", "commit", "-qm", "Synthetic baseline"])
        command([str(entire), "enable", "--agent", "claude-code", "--checkpoint-backend", backend,
                 "--telemetry=false", "--skip-push-sessions", "--no-init-repo", "--absolute-git-hook-path"])
        scripted_session(repo, scratch, command)
        refs = command(["git", "for-each-ref", "--format=%(refname)"]).decode().split()

        imported = import_repository(repo, destination / "import")
        # Entire links the external command into its managed plugin directory.
        command([str(entire), "plugin", "install", str(plugin)])
        listed = command([str(entire), "asr", "export", "--all", "--out", str(destination / "entire-asr")]).decode().split()
        agent_help = json.loads(command([str(entire), "agent-help", "asr", "export", "--json"]))
        rows = [json.loads(line) for line in Path(listed[0]).read_text().splitlines()]
        checkpoints = rows[0]["_meta"]["org.agentsessionrecord.importers"]["checkpoints"]
        same = [json.loads(line) for line in imported[0].read_text().splitlines()]
        invoked = rows[0]["_meta"]["org.agentsessionrecord.importers"].get("invokedBy")
        producer = rows[0]["producer"]
        # The command names itself as the producer. Every other field must match.
        for row in (rows[0], same[0]):
            row["_meta"]["org.agentsessionrecord.importers"].pop("invokedBy", None)
            row["producer"] = {**row["producer"], "name": None, "version": None}
        return {"backend": backend, "checkpointRefs": [ref for ref in refs if ref.startswith(("refs/entire/", "refs/heads/entire/"))],
                "checkpoints": [{"checkpoint": item["checkpoint"], "backend": item["backend"],
                                 "compactTranscriptStart": item["metadata"].get("compact_transcript_start")} for item in checkpoints],
                "sessions": len(listed), "records": dict(Counter(row["type"] for row in rows)),
                "inferences": sum(row["type"] == "inference" for row in rows),
                "invokedBy": invoked, "producer": producer,
                "matchesImporter": rows == same, "agentHelpCommand": agent_help["command"],
                "validation": {"importer": validate(destination / "import"), "entireAsr": validate(destination / "entire-asr")}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--entire", type=Path, required=True)
    parser.add_argument("--plugin", type=Path, required=True, help="an entire-asr executable from its release")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    entire, plugin = args.entire.resolve(), args.plugin.absolute()
    version = subprocess.run([str(entire), "version"], capture_output=True, text=True, check=True).stdout.split()[2]
    result = {"cliVersion": version, "scenario": "released CLI, scripted synthetic Claude Code hooks, two local Git commits per backend",
              "modelRequests": 0, "accounts": 0, "telemetry": False, "pushSessions": False,
              "runs": [run(entire, plugin, args.output_dir.resolve() / backend, backend) for backend in ("refs", "branch")]}
    args.summary.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({**result, "runs": [{k: v for k, v in run_.items() if k != "validation"} for run_ in result["runs"]]}, indent=1))


if __name__ == "__main__":
    main()
