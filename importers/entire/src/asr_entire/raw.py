"""Claude Code and Codex adapters for Entire's raw full.jsonl snapshots."""
from __future__ import annotations

import json

from asr_anthropic_compliance import blocks
from asr_importer_core import META, Stream, json_lines, native, text_parts, usage

AGENTS = ("claude-code", "codex")


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



def merge(stream: Stream, snapshots: list[tuple[dict, bytes | None]]) -> bytes:
    """Merge whole-session snapshots in checkpoint order without repeating work."""
    # full.jsonl is a whole-session snapshot. Merge only provable prefix
    # extensions. Divergent retained branches remain visible with a gap.
    merged = b""
    for metadata, transcript in snapshots:
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
    return merged
