import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from entire_store import fixture_store, git

ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = ROOT / "tools/validator/bin/asr-validate.js"
CLAUDE = "01KA2SYNTHETC0000000000CA1"


@pytest.fixture
def store(tmp_path):
    repo = tmp_path / "repo"
    fixture_store(repo)
    return repo


def plugin(repo, *args, cwd=None):
    env = {key: value for key, value in os.environ.items() if not key.startswith("ENTIRE_")}
    if repo:
        env["ENTIRE_REPO_ROOT"] = str(repo)
    return subprocess.run([sys.executable, "-m", "entire_asr", *args], capture_output=True, cwd=cwd, env=env)


def test_external_command_help_and_agent_help(store):
    result = plugin(store, "--help")
    assert result.returncode == 0 and b"entire asr [command]" in result.stdout
    assert plugin(store, "export", "--help").stdout.startswith(b"Selects sessions")
    described = json.loads(plugin(store, "agent-help", "--json").stdout)
    assert described["command"] == "entire asr" and described["subcommands"][0]["name"] == "export"
    flags = json.loads(plugin(store, "agent-help", "export", "--json").stdout)["flags"]
    assert {flag["name"] for flag in flags} == {"all", "checkpoint", "commit", "namespace", "out", "session", "transcript"}
    assert plugin(store, "agent-help", "export").stdout.startswith(b"entire asr export - ")
    assert plugin(store, "version").stdout.startswith(b"entire-asr ")


def test_external_command_exports_selected_sessions(store, tmp_path):
    single = plugin(store, "export", "--checkpoint", CLAUDE[:-1] + "1")
    assert single.returncode == 0, single.stderr
    (tmp_path / "single.jsonl").write_bytes(single.stdout)
    check = subprocess.run(["node", str(VALIDATOR), str(tmp_path / "single.jsonl")], capture_output=True, text=True)
    assert check.returncode == 0, check.stdout
    assert json.loads(single.stdout.splitlines()[0])["sessionId"] == "synthetic-claude-session"
    assert plugin(store, "export", "--session", "synthetic-claude").stdout == single.stdout
    # A commit's Entire-Checkpoint trailer selects its sessions.
    git(store, "commit", "-q", "--allow-empty", "-m", "Synthetic change\n\nEntire-Checkpoint: c0de0000a002")
    linked = plugin(store, "export", "--commit", "HEAD")
    assert json.loads(linked.stdout.splitlines()[0])["sessionId"] == "synthetic-codex-session"
    result = plugin(store, "export", "--all", "--out", str(tmp_path / "all"))
    assert result.returncode == 0 and len(result.stdout.splitlines()) == 5
    check = subprocess.run(["node", str(VALIDATOR), str(tmp_path / "all")], capture_output=True, text=True)
    assert check.returncode == 0, check.stdout
    assert plugin(store, "export", "--all", "--out", str(tmp_path / "all")).returncode == 1


@pytest.mark.parametrize("args, message", [
    (["export"], b"choose sessions"),
    (["export", "--bogus"], b"unknown flag"),
    (["export", "--all"], b"pass --out"),
    (["export", "--session", "synthetic-"], b"matches 5"),
    (["export", "--checkpoint", "ffff"], b"no local checkpoint"),
    (["export", "--commit", "--output"], b"not a commit"),
    (["export", "--all", "--transcript", "raw"], b"--transcript"),
    (["frobnicate"], b"unknown command"),
])
def test_external_command_errors_exit_one(store, args, message):
    result = plugin(store, *args)
    assert result.returncode == 1 and message in result.stderr and result.stdout == b""


def test_external_command_finds_the_repository_without_entire(store, tmp_path):
    result = plugin(None, "export", "--session", "synthetic-pi-session", cwd=store)
    assert result.returncode == 0 and b"synthetic-pi-session" in result.stdout.splitlines()[0]
    assert b"not inside a Git repository" in plugin(None, "export", "--all", cwd=tmp_path).stderr
