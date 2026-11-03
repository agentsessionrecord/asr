"""Recover framed records without interpreting stream text as instructions."""

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re


MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_LINE_BYTES = 16 * 1024 * 1024
MAX_RECORDS = 100_000


class SearchError(ValueError):
    """An export or load cannot be completed safely."""


KNOWN_TYPES = {"session", "session_info", "message", "tool_call", "tool_result", "approval",
               "file_change", "vcs", "inference", "gap"}


def _check_accessed_shapes(record):
    """Check fields used by this reader. The separate validator checks the schema."""
    def typed(key, shape, obj=record):
        if key in obj and not isinstance(obj[key], shape):
            raise SearchError("invalid_record_shape")

    for key in ("ts", "turnId", "inferenceId"):
        typed(key, str)
    typed("copiedFrom", dict)
    if "copiedFrom" in record:
        for key in ("session", "record"):
            typed(key, str, record["copiedFrom"])
        if not any(key in record["copiedFrom"] for key in ("session", "record")):
            raise SearchError("invalid_record_shape")
    kind = record["type"]
    if kind not in KNOWN_TYPES:
        return
    scalar_fields = {
        "tool_call": ("callId",), "tool_result": ("callId",), "approval": ("callId",),
        "file_change": ("callId", "path", "oldPath"), "vcs": ("callId",), "message": ("from",),
    }
    for key in scalar_fields.get(kind, ()):
        typed(key, str)
    object_fields = {
        "session": ("parent",), "session_info": ("usage", "cost", "agentSettings"),
        "tool_call": ("subagent",), "tool_result": ("subagent", "exec"),
        "file_change": ("before", "after"), "vcs": ("pr",), "inference": ("model", "usage", "cost"),
    }
    for key in object_fields.get(kind, ()):
        typed(key, dict)
    if kind == "session":
        for key in ("session", "kind", "record", "copiedThrough", "callId"):
            typed(key, str, record.get("parent", {}))
    if kind in ("tool_call", "tool_result"):
        typed("session", str, record.get("subagent", {}))
    list_fields = {
        "session": ("repos",), "session_info": ("repos",), "message": ("content",),
        "tool_call": ("locations",), "tool_result": ("content",), "file_change": ("edits",), "vcs": ("rewrites",),
    }
    for key in list_fields.get(kind, ()):
        typed(key, list)
        if any(not isinstance(item, dict) for item in record.get(key, [])):
            raise SearchError("invalid_record_shape")
    string_lists = {"session": ("missing",), "session_info": ("missing",), "vcs": ("parents",)}
    for key in string_lists.get(kind, ()):
        typed(key, list)
        if any(not isinstance(item, str) for item in record.get(key, [])):
            raise SearchError("invalid_record_shape")
    if kind in ("message", "tool_result"):
        for part in record.get("content", []):
            if part.get("type") == "reasoning" and "summary" in part:
                if not isinstance(part["summary"], list) or any(not isinstance(s, str) for s in part["summary"]):
                    raise SearchError("invalid_record_shape")
    if kind == "vcs":
        for key in ("commits",):
            typed(key, list, record.get("pr", {}))
            if any(not isinstance(item, str) for item in record.get("pr", {}).get(key, [])):
                raise SearchError("invalid_record_shape")
        for pair in record.get("rewrites", []):
            for key in ("from", "to"):
                typed(key, str, pair)
    for key, value in (record.get("agentSettings", {}) if kind == "session_info" else {}).items():
        if key in ("externalSandbox", "modelSettings") and value is not None and not isinstance(value, dict):
            raise SearchError("invalid_record_shape")
    if record["type"] == "tool_call" and "callId" not in record:
        raise SearchError("invalid_record_shape")
    if kind == "gap" and not isinstance(record.get("reason"), str):
        raise SearchError("invalid_record_shape")


def dumps(value):
    """Encode exact parsed decimals without a binary floating point round trip."""
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise SearchError("non_finite_number")
        return str(value)
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(k, ensure_ascii=True) + ":" + dumps(v)
                              for k, v in value.items()) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(dumps(v) for v in value) + "]"
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SearchError("duplicate_key")
        result[key] = value
    return result


def _constant(_):
    raise SearchError("non_json_number")


def loads(text):
    return json.loads(text, parse_float=Decimal, object_pairs_hook=_object,
                      parse_constant=_constant)


def component(value):
    result = []
    for char in value:
        if char in "%:# " or ord(char) < 32 or ord(char) == 127:
            result.extend(f"%{byte:02X}" for byte in char.encode("utf-8"))
        else:
            result.append(char)
    return "".join(result)


def session_ref(header):
    parts = [header["agent"]["name"]]
    if "namespace" in header:
        parts.append(component(header["namespace"]))
    parts.append(component(header["sessionId"]))
    return ":".join(parts)


def citation(ref, record_id):
    return ref + "#" + component(record_id)


def valid_index(value):
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,99}", value):
        raise SearchError("invalid_index_or_collection_name")
    return value


@dataclass
class Row:
    position: int
    record: dict
    raw: str


@dataclass
class Stream:
    ref: str
    rows: list[Row]
    issues: list[dict]
    sha256: str

    @property
    def header(self):
        return self.rows[0].record


def read_stream(path, max_line_bytes=MAX_LINE_BYTES):
    rows, issues, ids = [], [], set()
    digest = hashlib.sha256()
    position = 0
    size = 0
    with Path(path).open("rb") as source:
        while data := source.readline(max_line_bytes + 1):
            position += 1
            size += len(data)
            if size > MAX_INPUT_BYTES or position > MAX_RECORDS:
                raise SearchError('input_capacity')
            digest.update(data)
            if len(data) > max_line_bytes:
                complete = data.endswith(b"\n")
                while not complete:
                    rest = source.readline(max_line_bytes + 1)
                    size += len(rest)
                    if size > MAX_INPUT_BYTES:
                        raise SearchError('input_capacity')
                    digest.update(rest)
                    if not rest:
                        break
                    complete = rest.endswith(b"\n")
                issues.append({"position": position,
                               "code": "line_too_large" if complete else "incomplete_tail"})
                continue
            if not data.endswith(b"\n"):
                issues.append({"position": position, "code": "incomplete_tail"})
                break
            try:
                raw = data[:-1].decode("utf-8", errors="strict")
                record = loads(raw)
                if not isinstance(record, dict):
                    raise SearchError("not_an_object")
                if not all(isinstance(record.get(k), str) and record[k] for k in ("type", "id")):
                    raise SearchError("invalid_envelope")
                if len(record["id"]) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in record["id"]):
                    raise SearchError("invalid_record_id")
                _check_accessed_shapes(record)
                if record["id"] in ids:
                    raise SearchError("duplicate_record_id")
                if position > 1 and record["type"] == "session":
                    raise SearchError("extra_session_header")
            except (ValueError, UnicodeError, RecursionError) as error:
                code = str(error) if isinstance(error, SearchError) else "malformed_line"
                issues.append({"position": position, "code": code})
                continue
            ids.add(record["id"])
            rows.append(Row(position, record, raw))
    if not rows or rows[0].position != 1 or rows[0].record["type"] != "session":
        raise SearchError("missing_valid_first_header")
    header = rows[0].record
    if header.get("formatVersion") != "0.1":
        raise SearchError("unsupported_format_version")
    if not isinstance(header.get("agent"), dict) or not isinstance(header["agent"].get("name"), str):
        raise SearchError("invalid_agent")
    if not isinstance(header.get("sessionId"), str) or not header["sessionId"]:
        raise SearchError("invalid_session_id")
    if "namespace" in header and (not isinstance(header["namespace"], str) or not header["namespace"]):
        raise SearchError("invalid_namespace")
    parent = header.get("parent", {})
    if "copiedThrough" in parent and parent["copiedThrough"] not in {r.record["id"] for r in rows[1:]}:
        raise SearchError("unresolved_copied_boundary")
    return Stream(session_ref(header), rows, issues, digest.hexdigest())
