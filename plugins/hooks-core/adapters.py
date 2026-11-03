"""Normalize documented input fields. Hook responses are never decisions."""

import json
from pathlib import Path


def load(agent):
    path = Path(__file__).resolve().parent.parent / agent / "adapter.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    if config["agent"] != agent:
        raise ValueError("adapter identity mismatch")
    return config


def normalize(payload, config, event_name=None):
    if not isinstance(payload, dict):
        return None
    native = payload.get("hook_event_name", event_name)
    native = config.get("payload_event_aliases", {}).get(native, native)
    if native not in config["events"]:
        return None
    # Some protocols omit the event on stdin. Reject conflicts rather than
    # route by a guessed event name.
    if event_name is not None and native != event_name:
        return None
    event = {"hook_event_name": config["events"][native], "native_event": native}
    fields = {key: key for key in config["fields"]}
    fields.update(config.get("rename", {}))
    for source, dest in fields.items():
        if source in payload:
            event[dest] = payload[source]
    if config["agent"] == "copilot-cli":
        result = payload.get("toolResult")
        if isinstance(result, dict) and "textResultForLlm" in result:
            event["tool_response"] = result["textResultForLlm"]
    if config["agent"] == "cursor":
        for param in payload.get("model_params", []):
            if isinstance(param, dict) and param.get("id") == "effort" and isinstance(param.get("value"), str):
                event["effort"] = {"level": param["value"]}
    observations = {key: payload[key] for key in config.get("observations", []) if key in payload}
    agent = config["agent"]
    if agent == "devin" and native == "PostToolUse":
        response = payload.get("tool_response")
        if isinstance(response, dict):
            if type(response.get("success")) is bool:
                event["result_status"] = "completed" if response["success"] else "failed"
            if isinstance(response.get("error"), str) and response["error"]:
                event["error"] = response["error"]
    elif agent == "antigravity":
        tool = payload.get("toolCall")
        if isinstance(tool, dict):
            if "name" in tool:
                event["tool_name"] = tool["name"]
            if "args" in tool:
                event["tool_input"] = tool["args"]
        if native == "PostToolUse" and isinstance(payload.get("error"), str):
            event["result_status"] = "failed" if payload["error"] else "completed"
    elif agent == "auggie" and native == "PostToolUse":
        if type(payload.get("tool_is_error")) is bool:
            event["result_status"] = "failed" if payload["tool_is_error"] else "completed"
        elif isinstance(payload.get("tool_error"), str) and payload["tool_error"]:
            event["result_status"] = "failed"
    elif agent == "tabnine" and native == "AfterTool":
        # The documented post-tool input is the original request, not the
        # effective input. Do not promote it to ASR-076.
        event.pop("tool_input", None)
        response = event.pop("tool_response", None)
        if isinstance(response, dict):
            if "llmContent" in response:
                value = response["llmContent"]
                # Gemini-style parts are not MCP blocks. Only text-only
                # representations have a lossless ASR content mapping here.
                if isinstance(value, str):
                    event["tool_response"] = value
                elif isinstance(value, list) and all(isinstance(p, dict) and set(p) == {"text"}
                        and isinstance(p["text"], str) for p in value):
                    event["tool_response"] = [{"type": "text", "text": p["text"]} for p in value]
                else:
                    event.pop("tool_response", None)
            if isinstance(response.get("error"), str) and response["error"]:
                event["result_status"] = "failed"
                event["error"] = response["error"]
        if "tool_input" in payload:
            observations["originalToolInput"] = payload["tool_input"]
    if event.get("tool_name") in config["secret_tools"]:
        observations = {key: value for key, value in observations.items() if key == "tool_name"}
        event.pop("error", None)
    if observations:
        event["observations"] = observations
    return event
