"""Map Entire Transcript Format v1 lines to ASR records."""
from __future__ import annotations

import json
import re

from agent_session_record import derive_id
from asr_importer_core import MAX_RECORDS, Stream, count, loads

# Entire agent registry names, as transcript lines carry them.
ASR_NAMES = {"claude-code": "claude-code", "codex": "codex", "copilot-cli": "copilot-cli", "cursor": "cursor",
             "factoryai-droid": "droid", "opencode": "opencode", "pi": "pi", "antigravity": "antigravity",
             "Gemini CLI": "gemini-cli"}
# Agent type labels from checkpoint metadata, mapped to registry names.
REGISTRY_NAMES = {"Claude Code": "claude-code", "Codex": "codex", "Copilot CLI": "copilot-cli", "Cursor": "cursor",
                  "Factory AI Droid": "factoryai-droid", "OpenCode": "opencode", "Pi": "pi",
                  "Antigravity": "antigravity", "Gemini CLI": "Gemini CLI"}
UNKNOWN_AGENT = "org.agentsessionrecord.entire-unknown"
TOKEN_KEYS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
              "cache_write_5m_tokens", "cache_write_1h_tokens", "reasoning_tokens")
# Converters that write one line per model call with per-call usage, from 0.12.2.
PER_CALL = (0, 12, 2)
STATUS = {"success": "completed", "error": "failed"}


def version(value) -> tuple[int, int, int] | None:
    match = re.match(r"v?(\d+)\.(\d+)\.(\d+)", value) if isinstance(value, str) else None
    return tuple(int(part) for part in match.groups()) if match else None


def parse(data: bytes) -> list[tuple[bytes, dict | None]]:
    """Split a transcript into physical lines, the unit of compact_transcript_start."""
    if not data:
        return []
    pieces = data.split(b"\n")
    complete, tail = pieces[:-1], pieces[-1]
    if len(pieces) > MAX_RECORDS:
        raise ValueError("input_record_limit")
    result = []
    for raw in complete:
        try:
            line = loads(raw.decode("utf-8"))
        except (ValueError, UnicodeError, RecursionError):
            line = None
        if not isinstance(line, dict) or line.get("v") != 1 or not isinstance(line.get("type"), str) or not line["type"]:
            line = None
        result.append((raw, line))
    if tail:
        # An incomplete final line is never read as a complete record.
        result.append((tail, None))
    return result


def strip_results(content):
    if not isinstance(content, list):
        return content
    return [{key: value for key, value in block.items() if key != "result"}
            if isinstance(block, dict) and block.get("type") == "tool_use" else block for block in content]


def key(raw: bytes, line: dict | None):
    """Identify a line across checkpoint views, ignoring late tool results and usage."""
    if line is None:
        return ("raw", raw)
    if isinstance(line.get("id"), str) and line["id"]:
        return (line["type"], "id", line["id"])
    return (line["type"], "content", json.dumps(strip_results(line.get("content")), sort_keys=True, default=str))


def extends(earlier, later) -> bool:
    """True when a later checkpoint's line restates an earlier view of the same line."""
    (raw_a, a), (raw_b, b) = earlier, later
    if a is None or b is None:
        return raw_a == raw_b
    if a["type"] != b["type"]:
        return False
    if a.get("id") or b.get("id"):
        return a.get("id") == b.get("id")
    ca, cb = strip_results(a.get("content")), strip_results(b.get("content"))
    if isinstance(ca, list) and isinstance(cb, list):
        return cb[:len(ca)] == ca
    return ca == cb


class Mapper:
    """Write ASR records for normalized lines of one session, in file order."""

    def __init__(self, stream: Stream, agent: str):
        self.stream = stream
        self.agent = agent
        self.calls: dict[str, str] = {}
        self.inferences: list[dict] = []
        self.call_lines = 0
        self.usage_outside_calls = False
        self.assets = False
        self.user_text = False

    def gap(self, detail, meta, reason="unparseable", **fields):
        self.stream.gap(reason=reason, detail=detail, meta=meta, **fields)

    def line(self, raw: bytes, line: dict | None, meta: dict):
        if line is None:
            self.gap("A normalized transcript line could not be read.", {**meta, "line": raw.decode("utf-8", "replace")})
            return
        agent = line.get("agent") if isinstance(line.get("agent"), str) and line["agent"] else self.agent
        ts = line.get("ts")
        fields = {name: value for name, value in line.items() if name != "content"}
        if line["type"] == "user":
            self.content(line, "user", ts, {**meta, "line": fields}, source_id=user_id(line))
        elif line["type"] == "assistant":
            self.assistant(line, agent, ts, {**meta, "line": fields})
        else:
            # Readers keep unknown line types so that consumers can skip them.
            self.stream.add("session_info", ts=ts, missing=["native_events"], meta={**meta, "nativeRecord": line})

    def assistant(self, line, agent, ts, meta):
        has_usage = any(name in line for name in TOKEN_KEYS)
        current = (version(line.get("cli_version")) or (0, 0, 0)) >= PER_CALL
        identity = line.get("id") if isinstance(line.get("id"), str) and line["id"] else None
        provisional = None
        if agent == "claude-code" and identity:
            # Fragments of one message ID form one call. A continuation line
            # after tool results carries no usage. A reused ID with usage starts
            # a separate call, as Entire's fold keys it.
            if identity in self.calls and not has_usage:
                self.content(line, "assistant", ts, meta, inference=self.calls[identity])
                return
            provisional = identity
        elif agent == "pi" or (agent == "codex" and current and has_usage):
            provisional = identity or derive_id(self.stream.scope, "inference", len(self.stream.records), 0)
        elif has_usage:
            # Other converters write per-message counts without call boundaries.
            self.usage_outside_calls = True
        start = len(self.stream.records)
        self.content(line, "assistant", ts, meta, inference=provisional)
        if provisional is None:
            return
        fields = {}
        model = line.get("model")
        if isinstance(model, str) and model:
            # Claude Code reports the model that served the call. Codex and Pi
            # lines carry the model the agent configured for the request.
            fields["model"] = {"id": model} if agent == "claude-code" else {"requested": model}
        usage = call_usage(line, agent, current)
        if usage:
            fields["usage"] = usage
        actual = self.stream.add("inference", source_id=provisional, ts=ts,
                                 meta={key: value for key, value in meta.items() if key != "line"} |
                                 {"usage": {name: line[name] for name in TOKEN_KEYS if name in line},
                                  **({"messageId": identity} if identity else {})}, **fields)
        self.inferences.append(actual)
        if actual["id"] != provisional:
            for record in self.stream.records[start:]:
                if record.get("inferenceId") == provisional:
                    record["inferenceId"] = actual["id"]
        if agent == "claude-code":
            self.calls[identity] = actual["id"]

    def content(self, line, role, ts, meta, *, inference=None, source_id=None):
        content = line.get("content")
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        if content is None:
            content = []
        if not isinstance(content, list):
            self.gap("A normalized line has content in an unknown shape.", {**meta, "content": content}, ts=ts)
            return
        if role == "user":
            self.user_text = True
        parts: list[dict] = []
        state = {"meta": meta, "source": source_id}

        def first():
            # Line fields go on the first record made from the line.
            value, state["meta"] = state["meta"], {name: v for name, v in meta.items() if name != "line"}
            source, state["source"] = state["source"], None
            return value, source

        def flush():
            if parts:
                value, source = first()
                self.stream.add("message", source_id=source, ts=ts, meta=value, role=role, content=list(parts),
                                **({"inferenceId": inference} if inference else {}))
                parts.clear()

        for block in content:
            if not isinstance(block, dict):
                flush()
                self.gap("A normalized content block is not an object.", {**first()[0], "block": block}, ts=ts)
                continue
            kind = block.get("type", "text" if isinstance(block.get("text"), str) else None)
            if kind == "text" and isinstance(block.get("text"), str):
                parts.append({"type": "text", "text": block["text"]})
            elif kind == "image" and (part := self.image(block)) is not None:
                parts.append(part)
            elif kind == "tool_use":
                flush()
                self.tool(block, ts, first()[0], inference)
            else:
                flush()
                self.stream.gap(reason="unknown", detail="An unsupported content block is retained as metadata.",
                                ts=ts, meta={**first()[0], "block": block})
        flush()
        if not content and role == "user":
            value, source = first()
            self.stream.add("message", source_id=source, ts=ts, meta=value, role=role, content=[])

    def image(self, block):
        source = block.get("source") if isinstance(block.get("source"), dict) else {}
        mime = source.get("media_type", block.get("mimeType"))
        data = source.get("data", block.get("data"))
        if not isinstance(mime, str) or not mime:
            return None
        part = {"type": "image", "mimeType": mime}
        if isinstance(data, str) and data.startswith("entire-asset:"):
            # Image externalization moved the bytes to checkpoint assets.
            self.assets = True
        elif isinstance(data, str) and data:
            part["data"] = data
        return part

    def tool(self, block, ts, meta, inference):
        call_id = block.get("id") if isinstance(block.get("id"), str) and block["id"] else \
            derive_id(self.stream.scope, "call", len(self.stream.records), 0)
        result = block.get("result") if isinstance(block.get("result"), dict) else None
        fields = {"callId": call_id}
        if isinstance(block.get("name"), str):
            fields["name"] = block["name"]
        if "input" in block:
            fields["input"] = block["input"]
        if self.agent == "claude-code":
            fields["requestedBy"] = "model"
        target = result.get("file") if result else None
        if isinstance(target, dict) and isinstance(target.get("filePath"), str) and target["filePath"]:
            fields["locations"] = [{"path": target["filePath"]}]
        if inference:
            fields["inferenceId"] = inference
        self.stream.add("tool_call", source_id=block.get("id"), ts=ts,
                        meta={**meta, "block": {name: value for name, value in block.items() if name != "result"}}, **fields)
        if result is None:
            if "result" in block:
                self.gap("A tool result has an unknown shape.", {"block": block})
            return
        output = result.get("output")
        fields = {"callId": call_id, "status": STATUS.get(result.get("status"), "unknown")}
        # Entire writes an empty string when no text output was captured.
        if isinstance(output, str) and output:
            fields["content"] = [{"type": "text", "text": output}]
        detail = {name: value for name, value in result.items() if name != "output"}
        self.stream.add("tool_result", meta={**{k: v for k, v in meta.items() if k != "line"}, "result": detail}, **fields)

    def losses(self) -> list[str]:
        """Return defaults this session's records show were captured."""
        captured = []
        if self.inferences and not self.usage_outside_calls and all(
                {"inputTokens", "outputTokens"} <= set(record.get("usage", {})) for record in self.inferences):
            captured.append("usage")
        if self.inferences and all("model" in record for record in self.inferences):
            captured.append("model")
        return captured


def call_usage(line: dict, agent: str, current: bool) -> dict:
    """Normalize one call's usage to ASR inclusive totals, leaving unknowns absent."""
    valid = {name: line[name] for name in TOKEN_KEYS if count(line.get(name))}
    usage = {}
    if "output_tokens" in valid:
        usage["outputTokens"] = valid["output_tokens"]
    if "reasoning_tokens" in valid:
        usage["reasoningTokens"] = valid["reasoning_tokens"]
    if current and agent in ("claude-code", "codex", "pi"):
        # On these lines input_tokens excludes the line's cache reads and writes.
        if "cache_read_tokens" in valid:
            usage["cacheReadTokens"] = valid["cache_read_tokens"]
        if "cache_write_tokens" in valid:
            usage["cacheWriteTokens"] = valid["cache_write_tokens"]
        parts = ("input_tokens", "cache_read_tokens", "cache_write_tokens")
        if "input_tokens" in valid and all(name in valid or name not in line for name in parts):
            total = sum(valid.get(name, 0) for name in parts)
            if count(total):
                usage["inputTokens"] = total
    # Older lines hold fresh input only, or input whose cache share is unknown.
    return usage


def user_id(line: dict):
    if isinstance(line.get("id"), str) and line["id"]:
        return line["id"]
    content = line.get("content")
    if isinstance(content, list) and content and isinstance(content[0], dict):
        value = content[0].get("id")
        if isinstance(value, str) and value:
            return value
    return None
