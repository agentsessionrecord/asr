"""Read checkpoint Git objects without running a checkout or a recorded command."""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile

from asr_anthropic_compliance import blocks
from asr_importer_core import META, MAX_INPUT_BYTES, Stream, json_lines, loads, native, text_parts, usage

REF = "refs/heads/entire/checkpoints/v1"
AGENTS = {"Claude Code": "claude-code", "Codex": "codex", "claude-code": "claude-code", "codex": "codex"}


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


def checked_path(value: str, prefix: str) -> str:
    if not isinstance(value, str):
        raise ValueError("checkpoint pointer must be a Git path")
    path = value.lstrip("/")
    if "\\" in path or "\x00" in path or any(part in (".", "..") for part in path.split("/")) or not path.startswith(prefix + "/"):
        raise ValueError("checkpoint pointer escapes its checkpoint subtree")
    return path


def snapshots(repo: Path):
    revision = git(repo, "rev-parse", "--verify", REF + "^{commit}").decode().strip()
    tree = {}
    for entry in git(repo, "ls-tree", "-rz", "--full-tree", revision).split(b"\0"):
        if not entry:
            continue
        info, path = entry.split(b"\t", 1)
        mode, kind, oid = info.decode().split()
        if kind == "blob" and mode == "100644":
            tree[path.decode("utf-8")] = oid
    order = {}
    for index, path in enumerate(git(repo, "log", "--reverse", "--format=", "--name-only", revision).decode().splitlines()):
        if path:
            order[path] = index

    retained_bytes = 0
    def blob(path):
        nonlocal retained_bytes
        if path not in tree:
            return None
        data = git(repo, "cat-file", "blob", tree[path])
        retained_bytes += len(data)
        if retained_bytes > MAX_INPUT_BYTES:
            raise ValueError("checkpoint_byte_limit")
        return data

    result = []
    for root in tree:
        if not re.fullmatch(r"[0-9a-f]{2}/[0-9a-f]{10}/metadata\.json", root):
            continue
        summary = loads(blob(root).decode("utf-8"))
        if not isinstance(summary, dict):
            raise ValueError("invalid checkpoint summary")
        prefix = str(PurePosixPath(root).parent)
        sessions = summary.get("sessions")
        if not isinstance(sessions, list):
            # Legacy single-session checkpoints keep metadata at the root.
            sessions = [{"metadata": root, "transcript": prefix + "/full.jsonl"}]
        for pointers in sessions:
            if not isinstance(pointers, dict):
                raise ValueError("invalid checkpoint session pointer")
            metadata_path = checked_path(pointers.get("metadata"), prefix)
            raw_metadata = blob(metadata_path)
            if raw_metadata is None:
                raise ValueError("checkpoint session metadata is absent")
            metadata = loads(raw_metadata.decode("utf-8"))
            if not isinstance(metadata, dict):
                raise ValueError("invalid checkpoint session metadata")
            transcript_path = checked_path(pointers.get("transcript", str(PurePosixPath(metadata_path).parent / "full.jsonl")), prefix)
            transcript = blob(transcript_path)
            # Entire numbers additional raw chunks as full.jsonl.001, .002.
            chunks = sorted((path for path in tree if re.fullmatch(re.escape(transcript_path) + r"\.\d{3,}", path)),
                            key=lambda path: int(path.rsplit(".", 1)[1]))
            expected = [transcript_path + f".{index:03d}" for index in range(1, len(chunks) + 1)]
            if chunks != expected:
                raise ValueError("checkpoint transcript chunks are incomplete")
            if transcript is not None:
                transcript += b"".join(blob(path) for path in chunks)
            result.append((order.get(metadata_path, order.get(root, -1)), metadata_path, metadata, transcript, summary))
    return revision, sorted(result, key=lambda row: (row[0], row[1]))


def native_transcript(stream: Stream, data: bytes, agent: str):
    rows = list(json_lines(data))
    # A retained UUID can have several snapshots. Keep its completion point.
    last_uuid = {}
    last_call = {}
    for position, row in rows:
        if row and agent == "claude-code":
            if row.get("uuid"):
                last_uuid[str(row["uuid"])] = position
            message = row.get("message")
            if row.get("type") == "assistant" and isinstance(message, dict) and message.get("id"):
                last_call[str(message["id"])] = position
    requested_model = None
    settings = {}
    inference_ids = set()
    for position, row in rows:
        if row is None:
            stream.gap(meta={"sourceLine": position + 1})
            continue
        ts = row.get("timestamp")
        if agent == "claude-code":
            if row.get("uuid") and last_uuid[str(row["uuid"])] != position:
                continue
            message = row.get("message")
            if row.get("type") in ("user", "assistant") and isinstance(message, dict):
                inference = str(message["id"]) if row["type"] == "assistant" and message.get("id") else None
                # Reserve a stable provider ID for the later inference. Native
                # messages use UUIDs and calls use their own tool IDs.
                blocks(stream, message, source_id=row.get("uuid"), ts=ts,
                       meta={key: value for key, value in row.items() if key != "message"},
                       verified=row["type"] == "assistant", inference_id=inference, native_input=True)
                if inference and last_call[inference] == position:
                    fields = {}
                    if isinstance(message.get("model"), str) and message["model"]:
                        fields["model"] = {"provider": "anthropic", "id": message["model"]}
                    if isinstance(message.get("usage"), dict):
                        fields["usage"] = usage(message["usage"], anthropic=True)
                    if isinstance(message.get("stop_reason"), str):
                        fields["stopReason"] = message["stop_reason"]
                    actual = stream.add("inference", source_id=inference, ts=ts, meta={"messageUsage": message.get("usage")}, **fields)["id"]
                    if actual != inference:
                        # A native ID collision must not break links.
                        for record in stream.records:
                            if record.get("inferenceId") == inference:
                                record["inferenceId"] = actual
                if row.get("isCompactSummary") is True:
                    for record in stream.records:
                        if record["type"] == "message" and record.get("_meta", {}).get(META, {}).get("uuid") == row.get("uuid"):
                            record.update(origin="compaction", author="harness")
                    stream.gap("not_retained", "The source retains a compaction summary.", ts=ts)
            else:
                stream.add("session_info", ts=ts, missing=["native_events"], meta={"nativeRecord": row})
        elif agent == "codex":
            payload = row.get("payload")
            if not isinstance(payload, dict):
                stream.gap(ts=ts, meta={"nativeRecord": row})
                continue
            kind = row.get("type")
            if kind == "turn_context":
                requested_model = payload.get("model")
                settings = {target: payload[key] for key, target in (("effort", "reasoningEffort"), ("service_tier", "serviceTier")) if isinstance(payload.get(key), str)}
                policies = {target: payload[key] for key, target in (("approval_policy", "approval"), ("sandbox_policy", "sandbox")) if key in payload}
                if policies:
                    stream.add("session_info", ts=ts, agentSettings=policies, meta={"nativeRecord": row})
            elif kind == "response_item":
                item = payload.get("type")
                if item == "message" and payload.get("role") in ("user", "assistant", "system", "developer"):
                    content = text_parts(payload.get("content"))
                    shortened = isinstance(payload.get("content"), list) and len(content) != len(payload["content"])
                    if shortened:
                        stream.missing("content")
                    stream.add("message", source_id=payload.get("id"), ts=ts, role=payload["role"],
                               content=content, meta={"nativeRecord": row}, **({"truncated": True} if shortened else {}))
                elif item in ("function_call", "custom_tool_call") and isinstance(payload.get("call_id"), str):
                    value = payload.get("arguments", payload.get("input"))
                    fields = {"inputText": value} if isinstance(value, str) else {"input": value} if value is not None else {}
                    stream.add("tool_call", source_id=payload.get("id"), ts=ts, callId=payload["call_id"],
                               **({"name": payload["name"]} if isinstance(payload.get("name"), str) else {}),
                               requestedBy="model", meta={"nativeRecord": row}, **fields)
                elif item in ("function_call_output", "custom_tool_call_output"):
                    content = text_parts(payload.get("output"))
                    shortened = isinstance(payload.get("output"), list) and len(content) != len(payload["output"])
                    if shortened:
                        stream.missing("tool_output")
                    stream.add("tool_result", source_id=payload.get("id"), ts=ts, status="unknown",
                               **({"callId": payload["call_id"]} if isinstance(payload.get("call_id"), str) else {}),
                               content=content, meta={"nativeRecord": row}, **({"truncated": True} if shortened else {}))
                elif item == "reasoning":
                    summary = payload.get("summary")
                    reasoning = {"type": "reasoning", "visibility": "encrypted"}
                    if isinstance(summary, list):
                        reasoning.update(visibility="summary", summary=[part["text"] for part in summary if isinstance(part, dict) and isinstance(part.get("text"), str)])
                    stream.add("message", source_id=payload.get("id"), ts=ts, role="assistant", content=[reasoning])
                else:
                    stream.add("session_info", ts=ts, missing=["native_events"], meta={"nativeRecord": row})
            elif kind == "token_usage_record" and isinstance(payload.get("response_id"), str):
                if payload["response_id"] in inference_ids:
                    stream.add("session_info", ts=ts, missing=["duplicate_usage_observations"], meta={"nativeRecord": row})
                    continue
                inference_ids.add(payload["response_id"])
                fields = {"settings": settings}
                if isinstance(requested_model, str) and requested_model:
                    fields["model"] = {"requested": requested_model}
                if isinstance(payload.get("usage"), dict):
                    fields["usage"] = usage(payload["usage"])
                stream.add("inference", source_id=payload["response_id"], ts=ts, meta={"nativeRecord": row}, **fields)
            else:
                stream.add("session_info", ts=ts, missing=["native_events"], meta={"nativeRecord": row})
        else:
            stream.gap(reason="unknown", ts=ts, detail="This checkpoint's native agent format is unsupported.", meta={"nativeRecord": row})


def import_repository(repo: Path, output_dir: Path, *, namespace=None) -> list[Path]:
    revision, saved = snapshots(repo)
    grouped = defaultdict(list)
    for _, path, metadata, transcript, summary in saved:
        session = metadata.get("session_id")
        if not isinstance(session, str) or not session:
            raise ValueError("checkpoint metadata lacks its native session ID")
        agent = AGENTS.get(metadata.get("agent"), "org.agentsessionrecord.entire-unknown") if isinstance(metadata.get("agent"), str) else "org.agentsessionrecord.entire-unknown"
        grouped[(agent, session)].append((path, metadata, transcript, summary))
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    prepared = []
    for (agent, session), checkpoints in grouped.items():
        stream = Stream(agent, session, "entire-checkpoints-v1", namespace=namespace)
        stream.missing("checkpoint_history", "checkpoint_attribution", "assets")
        stream.header["_meta"] = {META: {"branchRevision": revision, "profile": "entire-v0.12.2", "checkpoints": [item[1] for item in checkpoints]}}
        # full.jsonl is a whole-session snapshot. Merge only provable prefix
        # extensions. Divergent retained branches remain visible with a gap.
        merged = b""
        for path, metadata, transcript, summary in checkpoints:
            if transcript is None:
                stream.gap("not_retained", "The checkpoint has no raw transcript.", meta={"metadata": metadata})
                continue
            if transcript.startswith(merged):
                merged = transcript
            elif merged.startswith(transcript):
                continue
            else:
                stream.missing("checkpoint_order")
                # Export both snapshots below. Matching native IDs, rather than
                # matching text, are the only deduplication key for the merge.
                stream.gap("unknown", "Retained checkpoint snapshots diverge. Their cross-checkpoint event order is unresolved.")
                old_rows = list(json_lines(merged))
                identities = {row.get("uuid") or row.get("payload", {}).get("id"): row for _, row in old_rows if row and isinstance(row.get("payload", {}), dict)}
                identities.pop(None, None)
                additional = []
                for _, row in json_lines(transcript):
                    identity = (row.get("uuid") or row.get("payload", {}).get("id")) if row and isinstance(row.get("payload", {}), dict) else None
                    if identity is None or identity not in identities:
                        additional.append(row)
                    elif identities[identity] != row:
                        stream.gap("unknown", "Conflicting retained native revisions are preserved here without merging their claims.",
                                   meta={"nativeRecord": row})
                merged += b"".join((json.dumps(native(row)) + "\n").encode() for row in additional)
        if merged:
            native_transcript(stream, merged, agent)
        name = hashlib.sha256((agent + "\0" + session).encode()).hexdigest() + ".jsonl"
        prepared.append((stream, output_dir / name))
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
