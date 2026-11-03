"""Shared ASR 0.1 projection for command hooks with JSON stdin."""

import hashlib
import json
import os
import re

from content import Content
from shared import VENDOR as META, EXTENSION, HOOK, repository_snapshot
from tool_records import tool_result
from file_changes import claude_file_change

VERSION = "0.1.0"
LOSSES = ["reasoning", "usage", "timestamps", "tool_output", "exit_codes",
          "file_changes", "commits", "subagents", "copies", "model", "approvals",
          "agent_settings", "cost", "tools", "instructions", "message_authorship",
          "message_person", "session_user", "triggers", "native_record_ids",
          "parent_lineage", "assistant_messages", "hook_input_rewrites", "tool_outcomes",
          "hook_outcomes", "hook_output_rewrites", "media", "elicitation_answers",
          "unmapped_hook_fields", "bounded_capture"]


def identifier(value):
    if isinstance(value, str) and 0 < len(value) <= 4096:
        return value
    return None


def filename(session):
    return session if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", session) else hashlib.sha256(session.encode()).hexdigest()


def project(session, parent, event, state, observed, config):
    rows = []
    name = event["hook_event_name"]
    content = Content(state["content"] == "full")
    from shared import credential_values
    content.values = (*content.values, *credential_values(event))
    source = {"event": event.get("native_event", name), "sessionId": parent}
    for key, dest in [("prompt_id", "promptId"), ("tool_use_id", "toolUseId"),
                      ("agent_id", "agentId"), ("message_id", "displayMessageId")]:
        value = identifier(event.get(key))
        if value:
            source[dest] = value
    if "timestamp" in event:
        source["nativeTimestamp"] = content.clean(event["timestamp"])

    def emit(record_type, **fields):
        position = state["position"]
        state["position"] += 1
        row = {"type": record_type, "id": "hook-" + str(position), "ts": observed, **fields}
        row.setdefault("_meta", {}).setdefault(META, {}).update(source)
        if content.redacted:
            row["truncated"] = True
        if source.get("promptId"):
            row["turnId"] = source["promptId"]
        rows.append(row)
        return row

    if state["position"] == 0:
        header = emit("session", formatVersion="0.1", agent={"name": config["agent"]},
                      sessionId=session, producer={"name": "asr-hooks-" + config["agent"],
                          "version": VERSION, "method": "recorder", "source": config["agent"] + "-hooks"},
                      missing=LOSSES + config.get("missing", []) +
                          ([] if content.full else ["content", "paths", "tool_names"]),
                      extensions=[EXTENSION])
        if name == "SessionStart" and (event.get("source") in config["new_session_sources"]
                                      or config.get("session_start_is_new")):
            header["startedAt"] = observed
            if isinstance(event.get("cwd"), str) and os.path.isabs(event["cwd"]):
                if content.full:
                    for key, value in repository_snapshot(event["cwd"]).items():
                        content.put(header, key, value)
        elif name != "SubagentStart":
            emit("gap", reason="not_recorded", detail="Capture began without a new session start. Earlier history is unavailable.")
        if isinstance(event.get("agent_version"), str):
            content.put(header["agent"], "version", event["agent_version"], record=header, public=True)
    if event.get("_redacted"):
        emit("gap", reason="redacted", count=1, detail="A hook observation contained a known credential in a native identity.")
        emit("session_info", missing=["redacted_content"])
        return rows
    if name == "MessageDisplay" and event.get("final") is not True:
        content.display(event, state)
        return rows

    hook = emit(HOOK)
    facts = hook["_meta"][META]
    for key, value in event.get("observations", {}).items():
        content.put(facts, key, value, record=hook)
    for key in ["source", "reason", "agent_type", "model", "from_model", "to_model",
                "requested_model", "failure_type", "error_type", "notification_type",
                "permission_suggestions", "parent_agent_id", "subagent_id", "parent_session_id",
                "tool_call_id", "task_name", "task_result", "task_error", "task",
                "stop_reason", "error", "last_assistant_message"]:
        if key in event:
            content.put(facts, key, event[key], record=hook)
    mode = event.get("permission_mode")
    settings = {}
    agent_type = event.get("agent_type")
    if (isinstance(agent_type, str) and agent_type != state.get("mode")
            and (name not in {"SubagentStart", "SubagentStop"}
                 or config.get("child_ids") and session != parent)):
        settings["mode"] = content.clean(agent_type)
        state["mode"] = settings["mode"]
    if isinstance(mode, str) and mode != state.get("approval"):
        settings["approval"] = content.clean(mode)
        if mode in config.get("asks_sometimes", []):
            settings["asks"] = "sometimes"
        state["approval"] = settings["approval"]
    if "mode" in settings and state.get("approval") in config.get("asks_sometimes", []):
        settings["asks"] = "sometimes"
    effort = event.get("effort")
    if isinstance(effort, dict) and isinstance(effort.get("level"), str):
        if effort["level"] != state.get("effort"):
            level = content.clean(effort["level"])
            settings["modelSettings"] = {"reasoningEffort": level}
            state["effort"] = level
    if settings:
        row = emit("session_info", agentSettings=settings)
        if content.redacted:
            row["truncated"] = True
    if isinstance(event.get("session_title"), str):
        if event["session_title"] != state.get("title") and content.full:
            info = emit("session_info")
            content.put(info, "title", event["session_title"])
            state["title"] = info.get("title")

    call = source.get("toolUseId")

    def request(payload, original=False):
        call_id = identifier(payload.get("tool_use_id"))
        if call_id and call_id in state["calls"]:
            return
        # Without native IDs, retain each request without guessing which result
        # answers it. Derived IDs identify requests only, never guessed pairs.
        row = emit("tool_call", callId=call_id or "unlinked-call-" + str(state["position"]))
        tool = payload.get("tool_name")
        if isinstance(tool, str):
            if content.full or tool in config["kinds"] or tool in config.get("agent_tools", []):
                content.put(row, "name", tool, public=True)
                if tool in config["kinds"]:
                    row["kind"] = config["kinds"][tool]
        if "tool_input" in payload and tool not in config["secret_tools"]:
            if original:
                content.put(row["_meta"][META], "requestedInput", payload["tool_input"], record=row)
            else:
                content.put(row, "input", payload["tool_input"])
        if call_id:
            state["calls"][call_id] = {"input": row["input"]} if "input" in row else {}
        if tool in config.get("agent_tools", []) and isinstance(payload.get("tool_input"), dict):
            subagent = {}
            for key, dest in [("subagent_type", "role"), ("description", "description")]:
                if isinstance(payload["tool_input"].get(key), str):
                    content.put(subagent, dest, payload["tool_input"][key], record=row)
            if subagent:
                row["subagent"] = subagent

    def result(payload, batch=False, fallback=False):
        call_id = identifier(payload.get("tool_use_id"))
        if call_id and call_id in state["results"]:
            return
        pending = state["pending"].pop(call_id, {}) if call_id else {}
        fields = tool_result(payload, pending, content, batch, config)
        initial = state["calls"].get(call_id, {})
        if ("input" in fields and "input" in initial
                and json.dumps(fields["input"], sort_keys=True) == json.dumps(initial["input"], sort_keys=True)):
            fields.pop("input")
        row = emit("tool_result", **fields)
        if call_id:
            row["callId"] = call_id
            row["_meta"][META]["toolUseId"] = call_id
            state["results"][call_id] = True
        if fallback:
            row.setdefault("_meta", {}).setdefault(META, {})["batchNotObserved"] = True

    if name == "UserPromptSubmit":
        row = emit("message", role="user", origin="prompt", content=[])
        content.message(row, event.get("prompt"))
    elif name == "MessageDisplay":
        value, shortened, redacted = content.display(event, state)
        row = emit("message", role="assistant", author="model", content=[])
        content.message(row, value)
        if shortened or redacted:
            row["truncated"] = True
        if shortened:
            emit("gap", reason="not_recorded", detail="Display chunks were missing or out of order.")
    elif name == "AssistantMessage":
        row = emit("message", role="assistant", author="model", content=[])
        content.message(row, event.get("message"))
    elif name == "Notification":
        row = emit("message", role="user", author="harness", origin="notice", content=[])
        content.message(row, event.get("message"))
    elif name == "PreToolUse":
        request(event, original=True)
    elif name in {"PostToolUse", "PostToolUseFailure"}:
        if call:
            request(event)
        if config.get("batch") and call and call not in state["results"]:
            pending = tool_result(event, {}, content, False, config)
            pending.setdefault("_meta", {}).setdefault(META, {})["firstObservedAt"] = observed
            state["pending"][call] = pending
        elif not config.get("batch") or not call:
            result(event)
    elif name == "PostToolBatch":
        for item in event.get("tool_calls", []):
            if isinstance(item, dict):
                call_id = identifier(item.get("tool_use_id"))
                if call_id:
                    request(item, original=True)
                result(item, batch=True)
    elif name == "PermissionDenied" and (call or isinstance(event.get("tool_name"), str)):
        row = emit("approval", decision="denied")
        if config.get("denied_by"):
            row["by"] = config["denied_by"]
        if call:
            row["callId"] = call
            if config.get("batch") and call not in state["results"]:
                state["pending"].setdefault(call, {})["status"] = "denied"
        else:
            content.put(row, "subject", event["tool_name"], public=True)
        native = {"hook_event_name": event.get("native_event", name)}
        if "reason" in event:
            content.put(native, "reason", event["reason"], record=row)
        row["native"] = native
    elif name == "PostCompact":
        row = emit("message", role="user", author="harness", origin="compaction", content=[])
        content.message(row, event.get("compact_summary"))
        # Context compaction does not destroy history already captured here.
    if config["agent"] == "claude-code" and content.full:
        change = claude_file_change(event)
        recorded = state.setdefault("changes", {})
        if change and (not call or call not in recorded):
            if call:
                recorded[call] = True
            cleaned = content.clean(change)
            row = emit("file_change", **cleaned)
            if content.redacted:
                row["truncated"] = True
    if name in {"Stop", "SubagentStop", "SessionEnd"}:
        for pending_call in list(state["pending"]):
            result({"tool_use_id": pending_call}, fallback=True)
    if name == "SessionEnd":
        emit("session_info", endedAt=observed)
    if content.redacted:
        emit("session_info", missing=["redacted_content"])
    return rows
