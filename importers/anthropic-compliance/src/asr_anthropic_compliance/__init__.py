"""Saved Compliance API pages and their documented content block mapping."""
from __future__ import annotations

from pathlib import Path

from asr_importer_core import META, MAX_INPUT_BYTES, Stream, loads, read_input, text_parts


def blocks(stream: Stream, message: dict, *, source_id=None, ts=None,
           meta=None, verified=False, inference_id=None, native_input=False):
    role = message.get("role")
    content = message.get("content")
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    if role not in ("user", "assistant", "system", "developer") or not isinstance(content, list):
        stream.gap(meta=meta, ts=ts)
        return
    if not content:
        stream.add("message", source_id=source_id, ts=ts, meta=meta, role=role, content=[])
    used_message_id = False
    for part in content:
        if not isinstance(part, dict):
            stream.gap(ts=ts)
            continue
        common = {"ts": ts, "meta": {**(meta or {}), "block": part}}
        if inference_id:
            common["inferenceId"] = inference_id
        shortened = part.get("truncated") is True
        if shortened:
            common["truncated"] = True
            stream.missing("content")
        kind = part.get("type")
        if kind == "text" and isinstance(part.get("text"), str):
            fields = {"role": role, "content": [{"type": "text", "text": part["text"]}]}
            if verified and role == "assistant":
                fields["author"] = "model"
            if role in ("system", "developer"):
                fields["origin"] = "instructions"
            provenance = (meta or {}).get("provenance") or {}
            if not isinstance(provenance, dict):
                provenance = {}
                stream.missing("provenance")
            if provenance.get("type") == "synthetic_marker":
                fields.update(author="harness", origin="notice")
            stream.add("message", source_id=source_id if not used_message_id else None, **common, **fields)
            used_message_id = True
        elif kind == "tool_use" and isinstance(part.get("id"), str) and part["id"]:
            fields = {"callId": part["id"]}
            if isinstance(part.get("name"), str):
                fields["name"] = part["name"]
            if verified and role == "assistant":
                fields["requestedBy"] = "model"
            if "input" in part:
                value = part["input"]
                if native_input:
                    fields["input"] = value
                elif isinstance(value, str):
                    if shortened:
                        fields["inputText"] = value
                    else:
                        try:
                            fields["input"] = loads(value)
                        except ValueError:
                            fields["inputText"] = value
                            stream.gap(ts=ts, detail="An untruncated tool input was not valid JSON.")
                else:
                    stream.gap(ts=ts, detail="The documented tool input was not a JSON string.")
            stream.add("tool_call", source_id=part["id"], **common, **fields)
        elif kind == "tool_result":
            fields = {"status": "failed" if part.get("is_error") is True else "completed" if part.get("is_error") is False else "unknown"}
            if isinstance(part.get("tool_use_id"), str) and part["tool_use_id"]:
                fields["callId"] = part["tool_use_id"]
            if "content" in part:
                fields["content"] = text_parts(part["content"])
                if not isinstance(part["content"], (str, list)) or isinstance(part["content"], list) and len(fields["content"]) != len(part["content"]):
                    common["truncated"] = True
                    stream.missing("tool_output")
            stream.add("tool_result", source_id=source_id if not used_message_id else None, **common, **fields)
            used_message_id = True
        elif kind in ("thinking", "redacted_thinking"):
            # Signatures and encrypted provider state must never reach metadata.
            reason = {"type": "reasoning", "visibility": "encrypted" if kind == "redacted_thinking" else "full"}
            if kind == "thinking" and isinstance(part.get("thinking"), str):
                reason["text"] = part["thinking"]
            stream.add("message", source_id=source_id if not used_message_id else None, ts=ts,
                       role=role, content=[reason], **({"inferenceId": inference_id} if inference_id else {}))
            used_message_id = True
        else:
            stream.gap(reason="unknown", detail="An unsupported content block is retained as metadata.",
                       source_id=source_id if not used_message_id else None, **common)
            used_message_id = True


def convert(pages: list[dict], *, namespace=None) -> Stream:
    if not pages or not isinstance(pages[0], dict):
        raise ValueError("expected saved local transcript pages")
    session = pages[0].get("session", {})
    if not isinstance(session, dict) or session.get("type") != "compliance_local_session" or session.get("product_surface") != "claude_code":
        raise ValueError("only documented Claude Code local sessions are supported")
    stream = Stream("claude-code", session.get("id"), "anthropic-compliance-local", namespace=namespace)
    # created_at is the earliest retained call, not necessarily session start.
    stream.header["_meta"] = {META: {"session": session, "profile": "local-sessions-docs-2026-11-01"}}
    user = session.get("user", {})
    if not isinstance(user, dict):
        user = {}
    identity = {target: str(user[key]) for key, target in (("id", "id"), ("email_address", "email")) if user.get(key) is not None and str(user[key])}
    if identity:
        stream.header["user"] = {**identity, "source": "agent_account"}
    seen = {}
    for page_index, page in enumerate(pages):
        if not isinstance(page, dict) or not isinstance(page.get("session"), dict) or page["session"].get("id") != session["id"] or not isinstance(page.get("data"), list):
            raise ValueError("transcript pages must belong to one native session")
        for message in page["data"]:
            if not isinstance(message, dict):
                stream.gap()
                continue
            mid = message.get("id")
            if isinstance(mid, str) and mid in seen:
                if seen[mid] != message:
                    stream.gap(detail="Conflicting revisions of a native message were not combined.")
                continue
            if isinstance(mid, str):
                seen[mid] = message
            provenance = message.get("provenance")
            meta = {key: message[key] for key in message if key != "content"}
            if provenance and not isinstance(provenance, dict):
                stream.gap(meta=meta)
                continue
            verified = "provenance" in message and provenance is None
            blocks(stream, message, source_id=mid, ts=message.get("created_at"), meta=meta, verified=verified)
            if provenance:
                kind, reason = provenance.get("type"), provenance.get("reason")
                if kind == "content_unavailable":
                    stream.records[-1]["truncated"] = True
                    mapped = {"retention_elapsed": "not_retained", "not_captured": "not_recorded", "client_aborted": "not_recorded"}.get(reason, "unknown") if isinstance(reason, str) else "unknown"
                    stream.gap(mapped, "The source reports unavailable message content.", ts=message.get("created_at"), meta={"provenance": provenance})
                elif kind == "synthetic_marker":
                    stream.gap("unknown", "A source marker replaces unavailable instructions or rewritten history.", ts=message.get("created_at"))
                elif kind != "client_asserted":
                    stream.missing("provenance")
        if page_index == len(pages) - 1 and page.get("next_page") is not None:
            stream.gap("not_retained", "The saved export ends before its pagination cursor.")
    return stream


def import_pages(paths: list[Path], output: Path, *, namespace=None):
    pages = []
    size = 0
    for path in paths:
        data = read_input(path)
        size += len(data)
        if size > MAX_INPUT_BYTES:
            raise ValueError("input_byte_limit")
        pages.append(loads(data.decode('utf-8')))
    convert(pages, namespace=namespace).write(output)
