"""The explicit Elastic-documented CODEX_LOG compatibility profile."""
from __future__ import annotations

from asr_importer_core import META, Stream, json_lines


def convert(data: bytes, *, session_id=None, namespace=None) -> Stream:
    rows = list(json_lines(data))
    sessions = {str(row["event_details"]["session_id"]) for _, row in rows
                if row and isinstance(row.get("event_details"), dict) and row["event_details"].get("session_id") is not None}
    if len(sessions) > 1 or session_id is not None and sessions - {session_id}:
        raise ValueError("split the input into one native session before importing")
    if session_id is None:
        if not sessions:
            raise ValueError("a native session ID is required")
        session_id = next(iter(sessions))
    stream = Stream("codex", session_id, "openai-codex-logs-elastic-profile", namespace=namespace)
    stream.header["_meta"] = {META: {"profile": "elastic-codex-log-2026-11-01", "liveTested": False}}
    seen = {}
    for position, row in rows:
        if row is None:
            stream.gap(meta={"sourceLine": position + 1})
            continue
        eid = row.get("event_id")
        if eid is not None and str(eid) in seen:
            if seen[str(eid)] != row:
                stream.gap(detail="Conflicting native events share an event ID.")
            continue
        if eid is not None:
            seen[str(eid)] = row
        details = row.get("event_details")
        if row.get("type") != "CODEX_LOG" or not isinstance(details, dict):
            stream.gap(reason="unknown", detail="A record outside the supported Codex profile is retained as metadata.", meta=row)
            continue
        if str(details.get("session_id")) != session_id:
            stream.gap(reason="unknown", detail="A log event has no session join key. It is not attributed to this session.", meta=row)
            continue
        event = row.get("event_type", details.get("detail_type"))
        ts = row.get("timestamp")
        common = {"ts": ts, "meta": row}
        if details.get("turn_id") is not None:
            common["turnId"] = str(details["turn_id"])
        if event == "PROMPT_RESPONSE_RECEIVED":
            # Elastic documents call_id as an MCP/tool call identifier. Neither
            # this event nor turn_id establishes individual model-call scope.
            # Keep model, settings and unscoped usage in the native metadata.
            emitted = False
            for key, role in (("prompt_text", "user"), ("response_text", "assistant")):
                if isinstance(details.get(key), str):
                    fields = {"role": role, "content": [{"type": "text", "text": details[key]}]}
                    stream.add("message", source_id=eid if not emitted else None, **common, **fields)
                    emitted = True
            if not emitted:
                stream.gap(reason="unknown", detail="The response event contains no mapped message content.", **common)
        elif event == "TOOL_CALL_COMPLETED":
            call_id = details.get("tool_call_id")
            if not isinstance(call_id, str) or not call_id:
                stream.gap(reason="unknown", detail="A completed tool event lacks a tool call ID.", **common)
                continue
            fields = {"callId": call_id}
            if isinstance(details.get("tool_name"), str):
                fields["name"] = details["tool_name"]
            if "tool_input" in details:
                if isinstance(details["tool_input"], str):
                    fields["inputText"] = details["tool_input"]
                else:
                    fields["input"] = details["tool_input"]
            stream.add("tool_call", meta={"completionSnapshot": row}, **fields)
            status = {"success": "completed", "failed": "failed", "error": "failed", "denied": "denied", "cancelled": "cancelled"}.get(details.get("status"), "unknown") if isinstance(details.get("status"), str) else "unknown"
            stream.add("tool_result", source_id=eid, callId=call_id, status=status, **common)
        elif "decision" in details:
            decision = {"approved": "approved", "approved_for_session": "approved", "denied": "denied", "timed_out": "cancelled"}.get(details["decision"]) if isinstance(details["decision"], str) else None
            if decision is None or not isinstance(details.get("call_id"), str) or not details["call_id"]:
                stream.gap(reason="unknown", detail="An unfamiliar approval decision is retained as metadata.", **common)
                continue
            fields = {"decision": decision, "callId": details["call_id"], "native": {"decision": details["decision"]}}
            if details["decision"] == "approved_for_session":
                fields["scope"] = "session"
            stream.add("approval", source_id=eid, **common, **fields)
        else:
            stream.gap(reason="unknown", detail="An unsupported log event is retained as metadata.", source_id=eid, **common)
    return stream
