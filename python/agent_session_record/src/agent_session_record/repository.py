"""Read repository facts only while observing an explicit live session start."""
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import urlsplit


def repository_snapshot(cwd):
    if not isinstance(cwd, str) or not os.path.isabs(cwd):
        return {}
    facts = {"cwd": cwd}
    deadline = time.monotonic() + 0.08
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")

    def git(*args):
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            result = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", cwd, *args],
                                    env=env, capture_output=True, timeout=remaining, check=False)
            if result.returncode or len(result.stdout) > 65536:
                return None
            return result.stdout.decode("utf-8").removesuffix("\n")
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return None

    path = git("rev-parse", "--show-toplevel")
    if not path or not Path(path).is_absolute():
        return facts
    repo = {"path": path}
    branch = git("symbolic-ref", "--quiet", "--short", "HEAD")
    head = git("rev-parse", "--verify", "HEAD")
    remote = git("config", "--get", "remote.origin.url")
    if branch:
        repo["branch"] = branch
    if head and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", head):
        repo["head"] = head
    # Omit authenticated or parameterized URLs rather than keeping credentials.
    if remote:
        try:
            parsed = urlsplit(remote)
            if not parsed.username and not parsed.password and not parsed.query and not parsed.fragment:
                repo["remote"] = remote
        except ValueError:
            pass
    facts["repos"] = [repo]
    return facts
