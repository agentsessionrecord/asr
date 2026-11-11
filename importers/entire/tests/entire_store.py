"""Build synthetic Entire checkpoint stores with Git plumbing, as Entire v0.13.2 lays them out."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

FIXTURES = Path(__file__).parent / "fixtures"
BRANCH = "refs/heads/entire/checkpoints/v1"
ENV = {"GIT_AUTHOR_NAME": "Synthetic Test", "GIT_AUTHOR_EMAIL": "synthetic@example.invalid",
       "GIT_COMMITTER_NAME": "Synthetic Test", "GIT_COMMITTER_EMAIL": "synthetic@example.invalid",
       "GIT_AUTHOR_DATE": "2026-10-01T12:00:00Z", "GIT_COMMITTER_DATE": "2026-10-01T12:00:00Z",
       "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def git(repo: Path, *args: str, data: bytes | None = None, env: dict | None = None) -> str:
    result = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-C", str(repo), *args], input=data,
                            env={**os.environ, **ENV, **(env or {})}, check=True, capture_output=True)
    return result.stdout.decode().strip()


def jsonl(rows) -> bytes:
    return b"".join(json.dumps(row, separators=(",", ":")).encode() + b"\n" for row in rows)


def init(repo: Path) -> Path:
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "commit", "-q", "--allow-empty", "-m", "Synthetic baseline")
    return repo


def write_tree(repo: Path, files: dict[str, bytes]) -> str:
    index = repo / ".git" / "synthetic-index"
    env = {"GIT_INDEX_FILE": str(index)}
    index.unlink(missing_ok=True)
    for path, content in sorted(files.items()):
        oid = git(repo, "hash-object", "-w", "--stdin", data=content)
        git(repo, "update-index", "--add", "--cacheinfo", f"100644,{oid},{path}", env=env)
    tree = git(repo, "write-tree", env=env)
    index.unlink()
    return tree


def checkpoint_files(checkpoint: dict, prefix: str, transcripts: dict) -> dict[str, bytes]:
    """Return one checkpoint subtree. prefix is "" at a ref root, or the branch shard path."""
    base = prefix + "/" if prefix else ""
    files, pointers = {}, []
    for index, session in enumerate(checkpoint["sessions"]):
        directory = f"{base}{index}"
        source = transcripts.get(session.get("transcript"), [])
        lines = [source[item] if isinstance(item, int) else item for item in session.get("lines", [])]
        files[f"{directory}/metadata.json"] = json.dumps(session["metadata"], indent=2).encode() + b"\n"
        pointer = {"metadata": f"/{directory}/metadata.json", "prompt": f"/{directory}/prompt.txt"}
        files[f"{directory}/prompt.txt"] = b""
        if "full" in session:
            files[f"{directory}/full.jsonl"] = session["full"]
            pointer["transcript"] = f"/{directory}/full.jsonl"
        if session.get("compact", True):
            files[f"{directory}/transcript.jsonl"] = jsonl(lines)
            pointer["compact_transcript"] = f"/{directory}/transcript.jsonl"
        pointers.append(pointer)
    summary = {"cli_version": "0.13.2", "checkpoint_id": checkpoint["id"], "strategy": "manual-commit", "branch": "main",
               "checkpoints_count": len(pointers), "files_touched": [], "sessions": pointers,
               **checkpoint.get("summary", {})}
    files[f"{base}metadata.json"] = json.dumps(summary, indent=2).encode() + b"\n"
    return files


def build(repo: Path, spec: dict, transcripts: dict | None = None) -> None:
    """Write each checkpoint copy in order: branch copies as v1 commits, ref copies as one ref each."""
    if transcripts is None:
        transcripts = load_transcripts()
    branch_files: dict[str, bytes] = {}
    branch_tip = None
    for checkpoint in spec["checkpoints"]:
        cid = checkpoint["id"]
        if checkpoint["backend"] == "git-branch":
            branch_files.update(checkpoint_files(checkpoint, cid[:2] + "/" + cid[2:], transcripts))
            tree = write_tree(repo, branch_files)
            parents = ["-p", branch_tip] if branch_tip else []
            branch_tip = git(repo, "commit-tree", tree, *parents, "-m", f"Checkpoint: {cid}")
            git(repo, "update-ref", BRANCH, branch_tip)
        else:
            tree = write_tree(repo, checkpoint_files(checkpoint, "", transcripts))
            commit = git(repo, "commit-tree", tree, "-m", f"Checkpoint: {cid}")
            git(repo, "update-ref", f"refs/entire/checkpoints/{cid[-2:]}/{cid}", commit)


def load_transcripts() -> dict:
    return {path.name.split(".")[0]: [json.loads(line) for line in path.read_text().splitlines()]
            for path in (FIXTURES / "normalized").glob("*.transcript.jsonl")}


def fixture_store(repo: Path) -> dict:
    spec = json.loads((FIXTURES / "checkpoints.json").read_text())
    init(repo)
    build(repo, spec)
    return spec
