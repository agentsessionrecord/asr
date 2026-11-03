"""Bounded, process-safe appends using the shared ASR writer for encoding."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path

from . import EVENTS

from agent_session_record.hooks import VENDOR
from agent_session_record.content import content_part, reasoning_part
from agent_session_record.privacy import credential_key, environment_secrets, redact_text, OPAQUE
from asr_plugin_core import Store, parts

MAX_INPUT = 1024 * 1024
MAX_STREAM = 16 * 1024 * 1024
CAP_DETAIL = "Recorder stream capacity reached. Further callbacks are not recorded."
MISSING = [
    "reasoning", "usage", "timestamps", "tool_output", "exit_codes",
    "file_changes", "commits", "subagents", "copies", "model", "approvals",
    "agent_settings", "tools", "instructions", "cost", "session_user",
    "message_person", "message_authorship", "triggers", "assistant_messages",
    "hook_outcomes", "automatic_reviewer_verdicts", "final_tool_output",
    "native_record_ids", "bounded_capture", "unmapped_hook_fields",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def decode(data: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))
    if not isinstance(value, dict):
        raise ValueError("Expected an object")
    return value


def scrub(value, secrets: tuple[str, ...]):
    """Exclude named credential fields and known credential values before staging."""
    if isinstance(value, dict):
        if value.get("type") in ("encrypted_content", "encrypted_reasoning"):
            return reasoning_part(visibility="encrypted")
        if value.get("type") in {"thinking", "redacted_thinking", "reasoning"}:
            value = content_part(value)
        return {key: "[redacted]" if credential_key(key) else scrub(item, secrets)
                for key, item in value.items() if key not in OPAQUE}
    if isinstance(value, list):
        return [scrub(item, secrets) for item in value]
    if isinstance(value, str):
        return redact_text(value, secrets, "[redacted]")
    return value


def project(payload: dict, previous: list[dict], receipt: str, full: bool, outcome: dict | None) -> list[dict]:
    """Keep callback occurrence distinct from execution and final approval decisions."""
    event = payload["hook_event_name"]
    envelope = {"ts": receipt}
    if isinstance(payload.get("turn_id"), str):
        envelope["turnId"] = payload["turn_id"]
    observed = {key: payload[key] for key in (
        "hook_event_name", "source", "reason", "model", "permission_mode",
        "tool_name", "tool_use_id", "agent_id", "agent_type", "trigger",
        "stop_hook_active", "status", "token_usage",
    ) if key in payload}
    if full and event == "PermissionRequest" and "tool_input" in payload:
        observed["tool_input"] = payload["tool_input"]
    if outcome is not None:
        observed["commandHookResponse"] = outcome if full else {"exitCode": outcome["exitCode"]}
        observed["responseIsProposal"] = True
    result = [{"type": VENDOR + "/hook", **envelope, "_meta": {VENDOR: observed}}]
    if outcome and outcome.get("outputOmitted"):
        result[0]["truncated"] = True
    if outcome is not None:
        return result

    settings = {}
    for record in previous:
        settings.update(record.get("agentSettings", {}))
    # Keep the compatibility approval label verbatim.
    if "permission_mode" in payload and settings.get("approval") != payload["permission_mode"]:
        result.append({"type": "session_info", **envelope,
                       "agentSettings": {"approval": payload["permission_mode"]}})
    call_id = payload.get("tool_use_id")
    calls = {r["callId"] for r in previous if r["type"] == "tool_call"}
    completed = {r.get("callId") for r in previous if r["type"] == "tool_result"}
    if event == "PreToolUse" and isinstance(call_id, str) and call_id not in calls:
        record = {"type": "tool_call", **envelope, "callId": call_id}
        if isinstance(payload.get("tool_name"), str):
            record["name"] = payload["tool_name"]
        if payload.get("tool_name") == "Bash":
            record["kind"] = "execute"
        elif payload.get("tool_name") == "apply_patch":
            record["kind"] = "edit"
        if full and "tool_input" in payload:
            record["_meta"] = {VENDOR: {"requestedInput": payload["tool_input"]}}
        result.append(record)
    if event == "PostToolUse" and call_id not in completed:
        record = {"type": "tool_result", **envelope, "status": "unknown"}
        if isinstance(call_id, str):
            record["callId"] = call_id
        response = payload.get("tool_response")
        if full:
            if "tool_input" in payload:
                record["input"] = payload["tool_input"]
            if isinstance(response, str):
                record["content"] = [{"type": "text", "text": response}]
            elif isinstance(response, dict) and str(payload.get("tool_name", "")).startswith("mcp__"):
                if isinstance(response.get("content"), list):
                    record["content"] = parts(response["content"]) or []
                record["_meta"] = {VENDOR: {"toolResponse": response}}
            elif "tool_response" in payload:
                record["_meta"] = {VENDOR: {"toolResponse": response}}
        if isinstance(response, dict) and str(payload.get("tool_name", "")).startswith("mcp__"):
            if type(response.get("isError")) is bool:
                record["status"] = "failed" if response["isError"] else "completed"
        result.append(record)
    if event == "UserPromptSubmit" and full and isinstance(payload.get("prompt"), str):
        result.append({"type": "message", **envelope, "role": "user", "origin": "prompt",
                       "content": [{"type": "text", "text": payload["prompt"]}]})
    # Stop may be retried and may continue the turn. Preserve its snapshot only.
    if event in ("Stop", "SubagentStop") and full and isinstance(payload.get("last_assistant_message"), str):
        observed["last_assistant_message"] = payload["last_assistant_message"]
    if event == "SessionEnd":
        result.append({"type": "session_info", **envelope, "endedAt": receipt})
    return result


def record(data: bytes, output: Path, *, full: bool = False, receipt: str | None = None,
           outcome: dict | None = None) -> bool:
    """Incremental, fail-open capture with the shared hook store."""
    store = Store("codex", "codex-command-hooks", output, full=full)
    try:
        if len(data) > MAX_INPUT:
            store.mark_loss()
            return False
        payload = decode(data)
        if payload.get("hook_event_name") not in EVENTS:
            return False
        native_id = payload.get("agent_id") or payload.get("session_id")
        if not isinstance(native_id, str) or not native_id:
            return False
        clean = scrub(payload, environment_secrets())
        if clean.get("session_id") != payload.get("session_id") or clean.get("agent_id") != payload.get("agent_id"):
            return False
        receipt = receipt or now()
        initial = (payload["hook_event_name"] == "SubagentStart" or
                   payload["hook_event_name"] == "SessionStart" and payload.get("source") in {"startup", "clear"})
        with store.transaction(native_id, receipt, start=initial, cwd=payload.get("cwd"),
                               extra_missing=tuple(MISSING)) as sink:
            if sink is None:
                return False
            state = sink.state
            previous = [{"type": "tool_call", "callId": cid} for cid in state.get("calls", [])]
            previous += [{"type": "tool_result", "callId": cid} for cid in sink.writer._results]
            previous += [{"type": "session_info", "agentSettings": state.get("settings", {})}]
            rows = project(payload, previous, receipt, full, outcome)
            if clean != payload:
                sink.append({"type": "session_info", "missing": ["redacted_content"]})
            if not full and "content" not in sink.writer._missing:
                sink.append({"type": "session_info", "missing": ["content", "paths"]})
            for row in rows:
                sink.append(row)
            return not getattr(sink.writer, "_capture_stopped", False)
    except Exception:
        store.mark_loss()
        return False
