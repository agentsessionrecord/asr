"""Fold structured outcomes with final model-facing batch output."""

from shared import session_reference

META = "org.agentsessionrecord.hooks"


def tool_result(event, pending, content, batch, config):
    row = dict(pending)
    name = event.get("hook_event_name")
    if name == "PostToolUse":
        row["status"] = config.get("post_status", "completed")
    elif name == "PostToolUseFailure":
        row["status"] = "interrupted" if event.get("is_interrupt") is True else "failed"
        if event.get("failure_type") == "permission_denied":
            row["status"] = "denied"
        if isinstance(event.get("error"), str):
            content.put(row, "error", {"message": event["error"]})
    row.setdefault("status", "unknown")
    if name == "PostToolUse" and event.get("result_status") in {"completed", "failed"}:
        row["status"] = event["result_status"]
        if isinstance(event.get("error"), str) and event["error"]:
            content.put(row, "error", {"message": event["error"]})
    if event.get("tool_name") in config["secret_tools"]:
        row["truncated"] = True
        return row
    duration = event.get("duration_ms")
    if type(duration) in (int, float) and 0 <= duration <= 2**53 - 1:
        row["durationMs"] = duration
    response = event.get("tool_response")
    if (batch or config.get("model_facing")) and "tool_response" in event:
        content.message(row, response)
    elif "tool_response" in event:
        content.put(row.setdefault("_meta", {}).setdefault(META, {}), "structuredOutput", response, record=row)
    if isinstance(response, dict):
        if event.get("tool_name") in config["shell_tools"]:
            if response.get("interrupted") is True:
                row["status"] = "interrupted"
            execution = {}
            for key in ["stdout", "stderr"]:
                if isinstance(response.get(key), str):
                    content.put(execution, key, response[key], record=row)
            if type(response.get("exitCode")) is int and abs(response["exitCode"]) <= 2**53 - 1:
                execution["exitCode"] = response["exitCode"]
            if execution:
                row["exec"] = execution
        if event.get("tool_name") in config.get("agent_tools", []) and isinstance(response.get("agentId"), str) and response["agentId"]:
            if content.clean(response["agentId"]) == response["agentId"]:
                row["subagent"] = {"session": session_reference(config["agent"], response["agentId"])}
            else:
                row["truncated"] = True
    # Batch inputs can be the original request even after a hook rewrite.
    if "tool_input" in event and not batch:
        content.put(row, "input", event["tool_input"])
        inputs = event["tool_input"]
        if isinstance(inputs, dict) and event.get("tool_name") in config["shell_tools"] and isinstance(inputs.get("command"), str):
            execution = row.setdefault("exec", {})
            content.put(execution, "command", inputs["command"], record=row)
            if not execution:
                row.pop("exec")
    return row
