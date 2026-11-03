"""Conservative JSON Lines recovery and exact ASR identities."""

from dataclasses import dataclass, field
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import unicodedata


MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_LINE_BYTES = 16 * 1024 * 1024
MAX_RECORDS = 100_000


def exact_json(value):
    """Serialize JSON numbers without passing decimals through binary floats."""
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(k) + ":" + exact_json(v) for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ",".join(exact_json(v) for v in value) + "]"
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("nonfinite_number")
        return str(value)
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def reject_constant(_):
    raise ValueError("nonfinite_number")


def parse_json(text):
    return json.loads(text, parse_float=Decimal, object_pairs_hook=unique_object,
                      parse_constant=reject_constant)


def component(value):
    return "".join("".join(f"%{byte:02X}" for byte in char.encode("utf-8"))
                   if char in "%:# " or unicodedata.category(char) == "Cc" else char
                   for char in value)


def session_ref(header):
    parts = [header["agent"]["name"]]
    if "namespace" in header:
        parts.append(component(header["namespace"]))
    return ":".join([*parts, component(header["sessionId"])])


def record_ref(reference, record_id):
    return reference + "#" + component(record_id)


def telemetry_id(reference, length):
    candidate, attempt = reference, 0
    while True:
        digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:length]
        if int(digest, 16):
            return digest
        attempt += 1
        candidate = reference + f"#{attempt}"


@dataclass
class Entry:
    data: dict
    line: int
    copied: bool = False


@dataclass
class Session:
    header: dict
    entries: list[Entry]
    diagnostics: list[dict] = field(default_factory=list)

    @property
    def reference(self):
        return session_ref(self.header)


def read_session(path: str | Path) -> Session:
    """Read complete records only. Diagnostics contain codes, never source text."""
    with Path(path).open('rb') as source:
        data = source.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES or data.count(b'\n') > MAX_RECORDS:
        raise ValueError('input_capacity')
    lines = data.split(b"\n")
    diagnostics = []
    if lines[-1]:
        diagnostics.append({"line": len(lines), "code": "incomplete_tail"})
    entries = []
    ids = set()
    for line, raw in enumerate(lines[:-1], 1):
        try:
            record = parse_json(raw.decode("utf-8"))
            if (not isinstance(record, dict) or not isinstance(record.get("type"), str)
                    or not isinstance(record.get("id"), str) or not record["id"]
                    or len(record["id"]) > 256
                    or any(unicodedata.category(c) == "Cc" for c in record["id"])):
                raise ValueError("invalid_envelope")
            if record["id"] in ids or (line > 1 and record["type"] == "session"):
                raise ValueError("duplicate_identity")
            for key in ("callId", "parentCallId", "inferenceId"):
                if key in record and not isinstance(record[key], str):
                    raise ValueError("invalid_reference")
            for key in ("parent", "subagent", "copiedFrom"):
                if key in record:
                    link = record[key]
                    if not isinstance(link, dict) or any(
                            k in link and not isinstance(link[k], str)
                            for k in ("session", "callId", "record", "copiedThrough")):
                        raise ValueError("invalid_reference")
            ids.add(record["id"])
            entries.append(Entry(record, line))
        except (ValueError, UnicodeError, RecursionError):
            diagnostics.append({"line": line, "code": "malformed_line"})
    if not entries or entries[0].line != 1 or entries[0].data.get("type") != "session":
        raise ValueError("invalid_header")
    header = entries[0].data
    if header.get("formatVersion") != "0.1":
        raise ValueError("unsupported_format_version")
    agent, producer = header.get("agent"), header.get("producer")
    if (not isinstance(agent, dict) or not isinstance(agent.get("name"), str)
            or not agent["name"] or not isinstance(producer, dict)
            or any(not isinstance(producer.get(k), str) or not producer[k]
                   for k in ("name", "version", "method"))
            or not isinstance(header.get("sessionId"), str) or not header["sessionId"]
            or ("namespace" in header and
                (not isinstance(header["namespace"], str) or not header["namespace"]))):
        raise ValueError("invalid_header")
    parent = header.get("parent", {})
    entries[0].copied = "copiedFrom" in header
    boundary = parent.get("copiedThrough") if isinstance(parent, dict) else None
    prefix_end = next((i for i, e in enumerate(entries[1:], 1)
                       if e.data["id"] == boundary), None)
    if boundary is not None and prefix_end is None:
        diagnostics.append({"line": 1, "code": "unresolved_copy_boundary"})
        prefix_end = len(entries)
    for i, entry in enumerate(entries[1:], 1):
        entry.copied = "copiedFrom" in entry.data or (prefix_end is not None and i <= prefix_end)
    return Session(header, entries, diagnostics)
