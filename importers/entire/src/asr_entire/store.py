"""Read Entire checkpoint stores from Git objects without a checkout or fetch."""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile

from asr_importer_core import MAX_INPUT_BYTES, loads

BRANCH = "refs/heads/entire/checkpoints/v1"
REFS = "refs/entire/checkpoints/"
HEX_ID = re.compile(r"[0-9a-f]{12}")
# A ULID's first character encodes the high timestamp bits, so it is 0 to 7.
ULID_ID = re.compile(r"[0-7][0-9ABCDEFGHJKMNPQRSTVWXYZ]{25}")
BRANCH_SUMMARY = re.compile(r"([0-9a-f]{2})/([0-9a-f]{10})/metadata\.json")


def git(repo: Path, *args: str) -> bytes:
    # Prevent inherited Git routing and object replacement from changing the
    # repository selected by the caller. Read commands do not invoke hooks.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_NO_LAZY_FETCH="1")
    # A large Git object must not be buffered without a bound in this process.
    with tempfile.TemporaryFile() as output:
        try:
            result = subprocess.run(["git", "--no-optional-locks", "--no-replace-objects", "-c", "core.fsmonitor=false",
                                     "-c", "log.showSignature=false", "-c", "core.hooksPath=" + os.devnull, "-C", str(repo), *args],
                                    env=env, stdout=output, stderr=subprocess.DEVNULL, check=False, timeout=30)
        except subprocess.TimeoutExpired:
            raise ValueError("local checkpoint Git read timed out") from None
        if result.returncode or output.tell() > MAX_INPUT_BYTES:
            raise ValueError("local checkpoint Git read failed or exceeded byte limit")
        output.seek(0)
        return output.read(MAX_INPUT_BYTES + 1)


def repository_root(start: Path) -> Path:
    return Path(git(start, "rev-parse", "--show-toplevel").decode("utf-8").strip())


def checked_path(value: str, prefix: str, *, strip: str | None = None) -> str:
    """Resolve a summary pointer inside its checkpoint subtree or reject it."""
    if not isinstance(value, str):
        raise ValueError("checkpoint pointer must be a Git path")
    path = value.lstrip("/")
    # Migration rewrites branch pointers to the ref root. Accept one that kept
    # its branch prefix, since it still names a path in the same subtree.
    if strip and path.startswith(strip + "/"):
        path = path[len(strip) + 1:]
    inside = path.startswith(prefix + "/") if prefix else bool(path)
    if "\\" in path or "\x00" in path or any(part in ("", ".", "..") for part in path.split("/")) or not inside:
        raise ValueError("checkpoint pointer escapes its checkpoint subtree")
    return path


@dataclass
class Blob:
    path: str
    oids: list[str]
    size: int


@dataclass
class SessionEntry:
    """One session slot in one stored copy of a checkpoint."""
    checkpoint: str
    backend: str
    revision: str
    index: int
    metadata_path: str
    metadata: dict
    summary: dict
    full: Blob | None = None
    compact: Blob | None = None
    session_id: str = field(init=False)

    def __post_init__(self):
        session = self.metadata.get("session_id")
        if not isinstance(session, str) or not session:
            raise ValueError("checkpoint metadata lacks its native session ID")
        self.session_id = session

    @property
    def compact_start(self) -> int | None:
        value = self.metadata.get("compact_transcript_start")
        return value if type(value) is int and value >= 0 else None

    @property
    def transcript_start(self) -> int:
        for key in ("checkpoint_transcript_start", "transcript_lines_at_start"):
            value = self.metadata.get(key)
            if type(value) is int and value > 0:
                return value
        return 0

    @property
    def cli_version(self) -> str | None:
        value = self.metadata.get("cli_version", self.summary.get("cli_version"))
        return value if isinstance(value, str) and value else None

    def describe(self) -> dict:
        return {"checkpoint": self.checkpoint, "backend": self.backend, "revision": self.revision,
                "session": self.index, "metadataPath": self.metadata_path,
                "fullTranscript": self.full.path if self.full else None,
                "normalizedTranscript": self.compact.path if self.compact else None,
                "metadata": self.metadata,
                **{key: self.summary[key] for key in ("commit_sha", "linked_commits") if key in self.summary}}


class Reader:
    """List checkpoint sessions and read their blobs within one byte budget per session."""

    def __init__(self, repo: Path):
        self.repo = repo
        self.budget = 0

    def blob(self, item: Blob | None) -> bytes | None:
        if item is None:
            return None
        data = b"".join(git(self.repo, "cat-file", "blob", oid) for oid in item.oids)
        self.budget += len(data)
        if len(data) > MAX_INPUT_BYTES or self.budget > MAX_INPUT_BYTES * 4:
            raise ValueError("checkpoint_byte_limit")
        return data

    def tree(self, revision: str) -> dict[str, tuple[str, int]]:
        tree = {}
        for entry in git(self.repo, "ls-tree", "-rlz", "--full-tree", revision).split(b"\0"):
            if not entry:
                continue
            info, path = entry.split(b"\t", 1)
            mode, kind, oid, size = info.decode().split()
            if kind == "blob" and mode == "100644":
                tree[path.decode("utf-8")] = (oid, int(size))
        return tree

    def refs(self) -> list[tuple[str, str, str]]:
        """Return (backend, ref, commit) for the local branch and checkpoint refs."""
        found = []
        listing = git(self.repo, "for-each-ref", "--format=%(objectname) %(objecttype) %(refname)", BRANCH, REFS)
        for line in listing.decode("utf-8").splitlines():
            oid, kind, name = line.split(" ", 2)
            if kind != "commit":
                continue
            if name == BRANCH:
                found.append(("git-branch", name, oid))
            elif checkpoint_from_ref(name):
                found.append(("git-refs", name, oid))
        return found

    def sessions(self) -> list[SessionEntry]:
        result = []
        for backend, ref, revision in self.refs():
            tree = self.tree(revision)
            if backend == "git-branch":
                for path in tree:
                    match = BRANCH_SUMMARY.fullmatch(path)
                    if match:
                        result += self.checkpoint(tree, match[1] + match[2], backend, revision, match[1] + "/" + match[2])
            elif "metadata.json" in tree:
                checkpoint = checkpoint_from_ref(ref)
                result += self.checkpoint(tree, checkpoint, backend, revision, "", strip=checkpoint[:2] + "/" + checkpoint[2:])
        return result

    def checkpoint(self, tree, checkpoint, backend, revision, prefix, strip=None) -> list[SessionEntry]:
        def json_blob(path):
            if path not in tree:
                return None
            value = loads(git(self.repo, "cat-file", "blob", tree[path][0]).decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("invalid checkpoint metadata")
            return value

        def blob(path, chunked=False):
            if path not in tree:
                return None
            oids, size = [tree[path][0]], tree[path][1]
            if chunked:
                # Entire numbers additional raw chunks as full.jsonl.001, .002.
                chunks = sorted((name for name in tree if re.fullmatch(re.escape(path) + r"\.\d{3,}", name)),
                                key=lambda name: int(name.rsplit(".", 1)[1]))
                if chunks != [path + f".{index:03d}" for index in range(1, len(chunks) + 1)]:
                    raise ValueError("checkpoint transcript chunks are incomplete")
                oids += [tree[name][0] for name in chunks]
                size += sum(tree[name][1] for name in chunks)
            return Blob(path, oids, size)

        root = (prefix + "/" if prefix else "") + "metadata.json"
        summary = json_blob(root)
        sessions = summary.get("sessions")
        if not isinstance(sessions, list):
            # Legacy single-session checkpoints keep metadata at the root.
            sessions = [{"metadata": root, "transcript": (prefix + "/" if prefix else "") + "full.jsonl"}]
        result = []
        for index, pointers in enumerate(sessions):
            if not isinstance(pointers, dict):
                raise ValueError("invalid checkpoint session pointer")
            metadata_path = checked_path(pointers.get("metadata"), prefix, strip=strip)
            metadata = json_blob(metadata_path)
            if metadata is None:
                raise ValueError("checkpoint session metadata is absent")
            directory = str(PurePosixPath(metadata_path).parent)
            full_path = checked_path(pointers.get("transcript", directory + "/full.jsonl"), prefix, strip=strip)
            # Older writers left out the pointer. The file name is Entire's own.
            compact_path = pointers.get("compact_transcript", directory + "/transcript.jsonl")
            compact_path = checked_path(compact_path, prefix, strip=strip)
            result.append(SessionEntry(checkpoint, backend, revision, index, metadata_path, metadata, summary,
                                       full=blob(full_path, chunked=True), compact=blob(compact_path)))
        return result


def checkpoint_from_ref(name: str) -> str | None:
    """Parse refs/entire/checkpoints/<shard>/<id> as Entire's ParseRef does."""
    if not name.startswith(REFS):
        return None
    parts = name[len(REFS):].split("/")
    if len(parts) != 2:
        return None
    shard, checkpoint = parts
    if not (HEX_ID.fullmatch(checkpoint) or ULID_ID.fullmatch(checkpoint)):
        return None
    return checkpoint if shard.lower() == checkpoint[-2:].lower() else None
