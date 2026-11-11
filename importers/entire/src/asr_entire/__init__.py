"""Read Entire checkpoints from Git objects into ASR without a checkout or a recorded command."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path

from asr_importer_core import META, Stream

from . import raw
from .normalized import ASR_NAMES, REGISTRY_NAMES, UNKNOWN_AGENT, Mapper, extends, key, parse
from .raw import native_transcript
from .store import BRANCH, REFS, Reader, SessionEntry, checked_path, checkpoint_from_ref, repository_root

__all__ = ["BRANCH", "REF", "REFS", "PROFILE", "Session", "checked_path", "checkpoint_from_ref", "convert", "discover",
           "import_repository", "map_lines", "native_transcript", "new_stream", "output_name", "repository_root",
           "write_all"]

REF = BRANCH
PROFILE = "entire-v0.13.2"
PRODUCER = {"name": "asr-import-entire", "version": "0.2.0", "method": "converter"}
TRANSCRIPTS = ("auto", "normalized", "full")


@dataclass
class Session:
    agent: str
    registry: str | None
    native_agent: str | None
    session_id: str
    entries: list[SessionEntry]
    shadowed: list[SessionEntry] = field(default_factory=list)

    @property
    def checkpoints(self) -> list[str]:
        return [entry.checkpoint for entry in self.entries]


def order_key(entry: SessionEntry):
    # Entire's own position markers grow through a session. Creation time and
    # the ID only break ties. Event timestamps never reorder records.
    start = entry.compact_start
    created = entry.metadata.get("created_at")
    return (entry.transcript_start, -1 if start is None else start,
            created if isinstance(created, str) else "", entry.checkpoint, entry.index)


def discover(repo: Path, reader: Reader | None = None) -> list[Session]:
    """Group every retained checkpoint copy by agent and native session ID."""
    reader = reader or Reader(repo)
    copies: dict[tuple, SessionEntry] = {}
    shadowed: dict[tuple, list[SessionEntry]] = {}
    for entry in reader.sessions():
        label = entry.metadata.get("agent") if isinstance(entry.metadata.get("agent"), str) else None
        slot = (label, entry.session_id, entry.checkpoint)
        previous = copies.get(slot)
        # Entire's readers try a checkpoint's own ref before the v1 branch,
        # including hex checkpoints migrated from the branch.
        if previous is None or (previous.backend == "git-branch" and entry.backend == "git-refs"):
            if previous is not None:
                shadowed.setdefault(slot, []).append(previous)
            copies[slot] = entry
        else:
            shadowed.setdefault(slot, []).append(entry)
    groups: dict[tuple, Session] = {}
    for (label, session, checkpoint), entry in copies.items():
        registry = REGISTRY_NAMES.get(label) if label else None
        agent = ASR_NAMES.get(registry, UNKNOWN_AGENT) if registry else UNKNOWN_AGENT
        group = groups.setdefault((label, session), Session(agent, registry, label, session, []))
        group.entries.append(entry)
        group.shadowed += shadowed.get((label, session, checkpoint), [])
    for group in groups.values():
        group.entries.sort(key=order_key)
    return sorted(groups.values(), key=lambda group: (group.agent, group.session_id, group.native_agent or ""))


def output_name(session: Session) -> str:
    # The hash is a file name, not a replacement session identity.
    return hashlib.sha256((session.agent + "\0" + session.session_id).encode()).hexdigest() + ".jsonl"


def convert(session: Session, reader: Reader, *, namespace=None, transcript="auto", invoked=None) -> Stream:
    if transcript not in TRANSCRIPTS:
        raise ValueError("unknown transcript source")
    reader.budget = 0
    last = session.entries[-1]
    use_raw = session.agent in raw.AGENTS and (
        (transcript == "full" and any(entry.full for entry in session.entries))
        or (transcript == "auto" and last.compact is None and last.full is not None))
    stream = new_stream(session.agent, session.session_id, "entire-full-jsonl" if use_raw else "entire-transcript-v1",
                        namespace=namespace)
    meta = {"profile": PROFILE, "transcript": "full" if use_raw else "normalized",
            "checkpoints": [entry.describe() for entry in session.entries]}
    if session.native_agent and session.agent == UNKNOWN_AGENT:
        meta["agent"] = session.native_agent
    if session.shadowed:
        meta["shadowedCopies"] = [{"checkpoint": entry.checkpoint, "backend": entry.backend, "revision": entry.revision}
                                  for entry in session.shadowed]
    if invoked:
        meta["invokedBy"] = invoked
    stream.header["_meta"] = {META: meta}
    if use_raw:
        stream.missing("assets")
        merged = raw.merge(stream, [(entry.metadata, reader.blob(entry.full)) for entry in session.entries])
        if merged:
            raw.native_transcript(stream, merged, session.agent)
        return stream
    normalized_session(stream, session, reader)
    return stream


def new_stream(agent: str, session_id: str, source: str, *, namespace=None) -> Stream:
    stream = Stream(agent, session_id, source, namespace=namespace)
    stream.header["producer"] = {**PRODUCER, "source": source}
    stream.missing("checkpoint_history", "checkpoint_attribution")
    return stream


def normalized_session(stream: Stream, session: Session, reader: Reader):
    current: list[tuple] = []  # (raw, line, checkpoint) or ("gap", entry)
    orphans: list[tuple] = []
    for entry in session.entries:
        data = reader.blob(entry.compact)
        if data is None:
            # A later self-contained view covers this checkpoint. Without one,
            # its content is missing here.
            current.append(("gap", entry))
            continue
        lines = parse(data)
        start = entry.compact_start
        real = [item for item in current if item[0] != "gap"]
        if start is None:
            # Checkpoints from CLIs before 0.8 store only their own delta.
            current += [(raw_line, line, entry.checkpoint) for raw_line, line in lines]
            stream.missing("checkpoint_deltas")
            continue
        if start > len(lines):
            stream.gap("unknown", "A checkpoint's transcript start marker is past the end of its transcript.",
                       meta={"checkpoint": entry.checkpoint, "compactTranscriptStart": start})
            start = len(lines)
        pairs = [(item[0], item[1]) for item in real]
        # The slice can repeat one merged line from the previous checkpoint.
        consistent = (start == len(real) and all(extends(pairs[i], lines[i]) for i in range(start))) or (
            start == len(real) - 1 and start < len(lines) and all(extends(pairs[i], lines[i]) for i in range(start + 1)))
        if not consistent:
            # Keep earlier content that this view no longer holds.
            held = {key(*line) for line in lines}
            orphans += [item for item in real if key(item[0], item[1]) not in held]
            earlier = {key(item[0], item[1]): item[2] for item in real}
            current = [(raw_line, line, earlier.get(key(raw_line, line)) if index < start else entry.checkpoint)
                       for index, (raw_line, line) in enumerate(lines)]
            continue
        current = [(raw_line, line, real[index][2] if index < len(real) else entry.checkpoint)
                   for index, (raw_line, line) in enumerate(lines)]

    map_lines(stream, session.registry or "", current, orphans)


def map_lines(stream: Stream, agent: str, lines: list[tuple], orphans: list[tuple] = ()) -> None:
    """Write records for assembled lines, then settle the session's declared losses."""
    mapper = Mapper(stream, agent)
    position = 0
    for item in lines:
        if item[0] == "gap":
            stream.gap("not_retained", "A checkpoint of this session has no normalized transcript.",
                       meta={"checkpoint": item[1].checkpoint})
            continue
        raw_line, line, checkpoint = item
        mapper.line(raw_line, line, {"transcriptLine": position, **({"checkpoint": checkpoint} if checkpoint else {})})
        position += 1
    if orphans:
        stream.missing("checkpoint_order")
        stream.gap("unknown", "Content that earlier checkpoints held and later checkpoints do not follows. "
                   "Its order relative to the records above is unresolved.")
        for raw_line, line, checkpoint in orphans:
            mapper.line(raw_line, line, {"checkpoint": checkpoint} if checkpoint else {})
    if mapper.assets:
        stream.missing("assets")
    if mapper.user_text:
        # Entire trims user text and removes IDE context tags.
        stream.missing("content")
    # Injected text and compaction summaries are not marked in this format.
    stream.missing("message_origin")
    captured = mapper.losses()
    stream.header["missing"] = [name for name in stream.header["missing"] if name not in captured]


def write_all(prepared: list[tuple[Stream, Path]]) -> list[Path]:
    if any(output.exists() for _, output in prepared):
        raise ValueError("an output session already exists")
    outputs = []
    try:
        for stream, output in prepared:
            stream.write(output)
            outputs.append(output)
    except BaseException:
        for output in outputs:
            output.unlink()
        raise
    return outputs


def import_repository(repo: Path, output_dir: Path, *, namespace=None, transcript="auto", select=None) -> list[Path]:
    reader = Reader(repo)
    sessions = discover(repo, reader)
    if select is not None:
        sessions = select(sessions)
    prepared = [(convert(session, reader, namespace=namespace, transcript=transcript), output_dir / output_name(session))
                for session in sessions]
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    return write_all(prepared)
