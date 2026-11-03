"""Opt-in content capture; exclude known credentials before any disk write."""

import os
import re
import base64
from shared import credential_key, environment_secrets, redact_text, OPAQUE, content_part


def valid_part(part):
    """Check core content shapes before putting native objects in core."""
    for key in ("author", "origin"):
        if key in part and not isinstance(part[key], str):
            return False
    kind = part["type"]
    if kind == "text":
        return isinstance(part.get("text"), str)
    if kind == "resource_link":
        if not all(isinstance(part.get(k), str) for k in ("uri", "name")):
            return False
        if any(k in part and not isinstance(part[k], str) for k in ("title", "description", "mimeType")):
            return False
        if "size" in part and (type(part["size"]) is not int or not 0 <= part["size"] <= 2**53 - 1):
            return False
    if kind == "resource":
        resource = part.get("resource")
        if not isinstance(resource, dict) or not isinstance(resource.get("uri"), str):
            return False
        if "text" not in resource and "blob" not in resource:
            return False
        if any(k in resource and not isinstance(resource[k], str) for k in ("text", "blob", "mimeType")):
            return False
        if "blob" in resource:
            try:
                base64.b64decode(resource["blob"], validate=True)
            except ValueError:
                return False
    if kind == "reasoning":
        if any(k in part and not isinstance(part[k], str) for k in ("text", "visibility")):
            return False
        if "summary" in part and (not isinstance(part["summary"], list) or not all(isinstance(s, str) for s in part["summary"])):
            return False
    return True



class Content:
    def __init__(self, full):
        self.full = full
        self.redacted = False
        self.values = environment_secrets()

    def clean(self, value):
        if isinstance(value, str):
            result = redact_text(value, self.values)
            self.redacted |= result != value
            return result
        if isinstance(value, list):
            return [self.clean(item) for item in value]
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                safe_key = self.clean(key)
                if credential_key(key):
                    result[safe_key] = "[REDACTED]"
                    self.redacted = True
                elif key not in OPAQUE:
                    result[safe_key] = self.clean(item)
                else:
                    self.redacted = True
            return result
        return value

    def put(self, target, key, value, record=None, public=False):
        record = target if record is None else record
        if self.full or public:
            cleaned = self.clean(value)
            target[key] = cleaned
            if cleaned != value:
                record["truncated"] = True
        else:
            record["truncated"] = True

    def message(self, row, value):
        if isinstance(value, str):
            if self.full:
                self.put(row, "content", [{"type": "text", "text": value}])
            else:
                row["truncated"] = True
        elif isinstance(value, list):
            parts = []
            for part in value:
                if not isinstance(part, dict) or not isinstance(part.get("type"), str):
                    row["truncated"] = True
                    continue
                if not valid_part(part):
                    row["truncated"] = True
                    continue
                if part["type"] in {"thinking", "redacted_thinking", "reasoning"}:
                    parts.append(content_part(part))
                    if part.get("visibility") in {"encrypted", "omitted"} and ("text" in part or "summary" in part):
                        row["truncated"] = True
                elif part["type"] in {"image", "audio"}:
                    # Native Anthropic media isn't the MCP core shape.
                    row["truncated"] = True
                else:
                    parts.append(content_part(part))
            if self.full:
                self.put(row, "content", parts)
            else:
                row["truncated"] = True
        else:
            row["truncated"] = True

    def display(self, event, state):
        key = event.get("message_id")
        index = event.get("index")
        delta = event.get("delta")
        if not isinstance(key, str) or not isinstance(delta, str) or type(index) is not int:
            return None, True, False
        entry = state["display"].setdefault(key, {"next": 0, "text": "", "lost": False, "redacted": False})
        entry["lost"] |= index != entry["next"]
        entry["next"] = index + 1
        if self.full:
            combined = entry["text"] + delta
            cleaned = self.clean(combined)
            entry["text"] = cleaned
            entry["redacted"] |= cleaned != combined
        if event.get("final") is True:
            del state["display"][key]
        self.redacted |= entry["redacted"]
        return entry["text"], entry["lost"], entry["redacted"]
