"""Read OTLP JSON and the data subset of Node console exporter output."""
from __future__ import annotations

import ast
from dataclasses import dataclass
import json
import re
from typing import Any, Iterator


class Number(str):
    """An uninterpreted JSON number token for exact storage."""


def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate object key")
        result[key] = value
    return result


def loads(text: str) -> Any:
    return json.loads(text, object_pairs_hook=pairs, parse_float=Number,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite number")))


def dumps(value: Any) -> str:
    if isinstance(value, Number):
        return str(value)
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + dumps(v) for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ",".join(map(dumps, value)) + "]"
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


_TOKEN = re.compile(r"\s*(?:(?P<string>'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\")|"
                    r"(?P<number>-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)|"
                    r"(?P<word>[A-Za-z_$][\w$]*)|(?P<punct>[{}\[\],:]))")
_SPACE = re.compile(r"\s*")


def console_value(text: str, start: int) -> tuple[Any, int]:
    """Parse data only. Functions, property access and expressions are rejected."""
    match = _TOKEN.match(text, start)
    if not match:
        raise ValueError("invalid console exporter data")
    token, end = match.group(0).strip(), match.end()
    if token in ("{", "["):
        result: Any = {} if token == "{" else []
        close = "}" if token == "{" else "]"
        while True:
            end = _SPACE.match(text, end).end()
            if text.startswith(close, end):
                return result, end + 1
            if isinstance(result, dict):
                key = _TOKEN.match(text, end)
                if not key or not (key.group("word") or key.group("string")):
                    raise ValueError("invalid console exporter key")
                name = ast.literal_eval(key.group("string")) if key.group("string") else key.group("word")
                end = key.end()
                end = _SPACE.match(text, end).end()
                if not text.startswith(":", end) or name in result:
                    raise ValueError("invalid or duplicate console exporter key")
                value, end = console_value(text, end + 1)
                result[name] = value
            else:
                value, end = console_value(text, end)
                result.append(value)
            end = _SPACE.match(text, end).end()
            if text.startswith(close, end):
                return result, end + 1
            if not text.startswith(",", end):
                raise ValueError("invalid console exporter delimiter")
            end += 1
    if match.group("string"):
        return ast.literal_eval(token), end
    if match.group("number"):
        return (Number(token) if any(c in token for c in ".eE") else int(token)), end
    if token in ("true", "false", "null", "undefined"):
        return {"true": True, "false": False, "null": None, "undefined": None}[token], end
    raise ValueError("console exporter expressions are not supported")


def documents(text: str) -> Iterator[Any]:
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    decoder = json.JSONDecoder(object_pairs_hook=pairs, parse_float=Number,
                               parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite number")))
    offset = 0
    while offset < len(text):
        offset = _SPACE.match(text, offset).end()
        if offset == len(text):
            break
        try:
            value, offset = decoder.raw_decode(text, offset)
        except json.JSONDecodeError:
            value, offset = console_value(text, offset)
        yield value


def any_value(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    for key in ("stringValue", "string_value", "boolValue", "bool_value", "intValue", "int_value", "doubleValue", "double_value"):
        if key in value:
            return value[key]
    for key in ("kvlistValue", "kvlist_value"):
        if key in value:
            return attributes(value[key].get("values", []))
    for key in ("arrayValue", "array_value"):
        if key in value:
            return [any_value(v) for v in value[key].get("values", [])]
    return value


def attributes(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, list):
        raise ValueError("invalid telemetry attributes")
    return pairs([(v["key"], any_value(v["value"])) for v in value])


@dataclass
class Event:
    name: str
    attrs: dict[str, Any]
    resource: dict[str, Any]
    timestamp: Any = None


def events(value: Any, resource: dict[str, Any] | None = None) -> Iterator[Event]:
    if isinstance(value, list):
        for item in value:
            yield from events(item, resource)
        return
    if not isinstance(value, dict):
        raise ValueError("expected telemetry object")
    resource = {**(resource or {}), **attributes(value.get("resource", {}).get("attributes", {}))}
    for key in ("resourceLogs", "resource_logs", "scopeLogs", "scope_logs", "instrumentationLibraryLogs", "instrumentation_library_logs", "logRecords", "log_records"):
        if key in value:
            for child in value[key]:
                yield from events(child, resource)
            return
    attrs = attributes(value.get("attributes", {}))
    body = any_value(value.get("body"))
    # Rust tracing can fill eventName with its source callsite. The explicit
    # business-event attribute identifies the Codex event in that case.
    name = attrs.get("event.name") or value.get("eventName") or value.get("event_name") or body
    if name in ("tool_decision", "safety_event") and isinstance(body, str) and body.startswith("claude_code."):
        name = body
    if name in ("claude_code.tool_decision", "claude_code.safety_event", "codex.tool_decision"):
        yield Event(name, attrs, resource, value.get("timeUnixNano", value.get("time_unix_nano", value.get("timestamp"))))
