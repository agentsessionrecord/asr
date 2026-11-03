import subprocess
from unittest import mock

from agent_session_record.repository import repository_snapshot


def test_start_snapshot_handles_subdirectories_worktrees_and_detached_heads(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()
    git("init", "-q", "-b", "synthetic")
    git("-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid", "commit", "-q", "--allow-empty", "-m", "Baseline")
    git("remote", "add", "origin", "https://example.invalid/team/repo.git")
    sub = tmp_path / "sub"
    sub.mkdir()
    first = repository_snapshot(str(sub))
    assert first == {"cwd": str(sub), "repos": [{"path": str(tmp_path), "branch": "synthetic", "head": git("rev-parse", "HEAD"), "remote": "https://example.invalid/team/repo.git"}]}
    linked = tmp_path / "linked"
    git("worktree", "add", "-q", "--detach", str(linked))
    other = repository_snapshot(str(linked))
    assert other["repos"][0]["path"] == str(linked)
    assert other["repos"][0]["head"] == first["repos"][0]["head"]
    assert "branch" not in other["repos"][0]
    for remote in ["https://synthetic:password@example.invalid/repo", "https://example.invalid/repo?token=synthetic-secret"]:
        git("remote", "set-url", "origin", remote)
        assert "remote" not in repository_snapshot(str(sub))["repos"][0]


def test_git_failures_and_non_repositories_keep_only_observed_cwd(tmp_path):
    assert repository_snapshot(str(tmp_path)) == {"cwd": str(tmp_path)}
    assert repository_snapshot("relative") == {}
    for failure in [FileNotFoundError(), subprocess.TimeoutExpired("git", 0.08)]:
        with mock.patch("agent_session_record.repository.subprocess.run", side_effect=failure):
            assert repository_snapshot(str(tmp_path)) == {"cwd": str(tmp_path)}
