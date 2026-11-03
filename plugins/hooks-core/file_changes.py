"""Claude Code success objects supply edit evidence without reading file contents."""


def claude_file_change(event):
    if event.get("hook_event_name") != "PostToolUse":
        return None
    output, inputs = event.get("tool_response"), event.get("tool_input", {})
    if not isinstance(output, dict) or not isinstance(inputs, dict):
        return None
    tool = event.get("tool_name")
    if tool not in {"Write", "Edit", "MultiEdit"}:
        return None
    path = output.get("filePath", inputs.get("file_path"))
    if not isinstance(path, str) or not path:
        return None
    status = "proposed" if output.get("staged") is True else "applied"
    change = {"path": path, "op": "modify", "status": status}
    if event.get("tool_use_id"):
        change["callId"] = event["tool_use_id"]
    before = output.get("originalFile")
    if isinstance(before, str):
        change["before"] = {"text": before}
    if tool == "Write":
        # The native success discriminator distinguishes a new file from an update.
        if output.get("type") not in {"create", "update"}:
            return None
        change["op"] = "add" if output["type"] == "create" else "modify"
        after = output.get("content", inputs.get("content"))
        if isinstance(after, str):
            change["after"] = {"text": after}
    else:
        edits = output.get("edits", inputs.get("edits")) if tool == "MultiEdit" else [output]
        if not isinstance(edits, list):
            return None
        mapped = []
        for item in edits:
            if not isinstance(item, dict):
                return None
            old = item.get("oldString", item.get("old_string"))
            new = item.get("newString", item.get("new_string"))
            if tool == "Edit":
                old = old if old is not None else inputs.get("old_string")
                new = new if new is not None else inputs.get("new_string")
            if not isinstance(old, str) or not isinstance(new, str):
                return None
            mapped.append({"oldText": old, "newText": new})
        if not mapped:
            return None
        change["edits"] = mapped
    return change
