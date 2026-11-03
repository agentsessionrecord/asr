"""Read JSONL without evaluating content or losing decimal precision."""

from dataclasses import dataclass, field
from decimal import Decimal
import json
from pathlib import Path


MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_LINE_BYTES = 16 * 1024 * 1024
MAX_RECORDS = 100_000


def json_text(value):
    """Serialize exact JSON numbers, including unknown vendor values."""
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("non_finite_number")
        return str(value)
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(k) + ":" + json_text(v) for k, v in value.items()) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(json_text(v) for v in value) + "]"
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def bad_constant(_):
    raise ValueError("non_finite_number")


def valid_shapes(record):
    for key in ("callId", "turnId", "inferenceId", "ts", "name", "kind", "from", "path", "oldPath", "op", "status", "decision", "by", "scope"):
        if key in record and not isinstance(record[key], str):
            return False
    for key in ("parent", "copiedFrom", "subagent", "_meta", "exec", "agentSettings"):
        if key in record and not isinstance(record[key], dict):
            return False
    if "missing" in record and (not isinstance(record["missing"], list) or any(not isinstance(item, str) for item in record["missing"])):
        return False
    settings = record.get("agentSettings", {})
    if "exitCode" in record.get("exec", {}) and type(record["exec"]["exitCode"]) is not int:
        return False
    if any(key in settings and settings[key] is not None and not isinstance(settings[key], dict) for key in ("modelSettings", "externalSandbox")):
        return False
    for key in ("parent", "copiedFrom", "subagent"):
        value = record.get(key, {})
        if any(name in value and not isinstance(value[name], str) for name in ("session", "record", "copiedThrough")):
            return False
    return True


@dataclass
class Session:
    records: list[dict]
    diagnostics: list[dict] = field(default_factory=list)


def read_session(path: str | Path) -> Session:
    records, diagnostics, ids = [], [], set()
    with Path(path).open('rb') as source:
        data = source.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES or data.count(b'\n') > MAX_RECORDS:
        raise ValueError('input_capacity')
    lines = data.split(b"\n")
    if lines[-1]:
        diagnostics.append({"code": "incomplete_tail", "line": len(lines)})
    for number, raw in enumerate(lines[:-1], 1):
        try:
            record = json.loads(raw.decode("utf-8"), parse_float=Decimal,
                                parse_constant=bad_constant, object_pairs_hook=unique_object)
            if not isinstance(record, dict):
                raise ValueError("not_object")
            rid = record.get("id")
            if not isinstance(record.get("type"), str) or not isinstance(rid, str) or not rid or len(rid) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in rid):
                raise ValueError("invalid_envelope")
            if rid in ids:
                raise ValueError("duplicate_id")
            if number != 1 and record["type"] == "session":
                raise ValueError("extra_header")
            if not valid_shapes(record):
                raise ValueError("invalid_shapes")
        except (ValueError, UnicodeError):
            if number == 1:
                raise ValueError("invalid_header") from None
            diagnostics.append({"code": "malformed_line", "line": number})
            continue
        ids.add(rid)
        records.append(record)
    if not records or records[0].get("type") != "session":
        raise ValueError("missing_header")
    header = records[0]
    if header.get("formatVersion") != "0.1":
        raise ValueError("unsupported_version")
    if not isinstance(header.get("agent"), dict) or not isinstance(header["agent"].get("name"), str) or not isinstance(header.get("sessionId"), str) or not header["sessionId"] or ("namespace" in header and not isinstance(header["namespace"], str)):
        raise ValueError("invalid_header")
    return Session(records, diagnostics)
