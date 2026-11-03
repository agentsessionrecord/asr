"""Recover complete JSONL records without interpreting recorded commands or URLs."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import simplejson as json


MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_LINE_BYTES = 16 * 1024 * 1024
MAX_RECORDS = 100_000


class ExportError(ValueError):
    """A safe, content-free error code."""


@dataclass
class Stream:
    header: dict
    records: list[tuple[int, dict, str]]
    digest: str
    source_index: int
    diagnostics: list[dict]


def encode_component(value: str) -> str:
    return "".join(
        "".join(f"%{byte:02X}" for byte in char.encode("utf-8"))
        if char in "%:# " or ord(char) < 32 or 127 <= ord(char) <= 159 else char
        for char in value
    )


def session_ref(header: dict) -> str:
    parts = [header["agent"]["name"]]
    if "namespace" in header:
        parts.append(encode_component(header["namespace"]))
    parts.append(encode_component(header["sessionId"]))
    return ":".join(parts)


def record_ref(session: str, record: str) -> str:
    return session + "#" + encode_component(record)


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, use_decimal=True, separators=(",", ":"))


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate-key")
        result[key] = value
    return result


def read_stream(path: Path, source_index: int) -> Stream:
    records, diagnostics, ids = [], [], set()
    digest = sha256()
    size = 0
    with path.open("rb") as handle:
        for position, line in enumerate(iter(lambda: handle.readline(MAX_LINE_BYTES + 1), b''), 1):
            size += len(line)
            if len(line) > MAX_LINE_BYTES or size > MAX_INPUT_BYTES or position > MAX_RECORDS:
                raise ExportError('input_capacity')
            digest.update(line)
            if not line.endswith(b"\n"):
                diagnostics.append(dict(source_index=source_index, line=position,
                                        code="incomplete-tail", severity="warning"))
                continue
            try:
                raw = line[:-1].decode("utf-8")
                item = json.loads(raw, use_decimal=True, object_pairs_hook=unique_object)
                if not isinstance(item, dict) or not isinstance(item.get("type"), str):
                    raise ValueError("record-shape")
                ident = item.get("id")
                if (not isinstance(ident, str) or not ident or len(ident) > 256
                        or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in ident)):
                    raise ValueError("record-id")
                if ident in ids:
                    raise ExportError("duplicate-record-id")
                ids.add(ident)
                records.append((position, item, raw))
            except (ValueError, UnicodeError) as error:
                if isinstance(error, ExportError):
                    raise
                diagnostics.append(dict(source_index=source_index, line=position,
                                        code="malformed-line", severity="error"))
    if not records or records[0][0] != 1 or records[0][1]["type"] != "session":
        raise ExportError("missing-header")
    header = records[0][1]
    if header.get("formatVersion") != "0.1":
        raise ExportError("unsupported-version")
    try:
        ref = session_ref(header)
        if not ref or not isinstance(header["sessionId"], str):
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise ExportError("invalid-session-identity") from None
    if any(item["type"] == "session" for _, item, _ in records[1:]):
        raise ExportError("multiple-headers")
    return Stream(header, records, digest.hexdigest(), source_index, diagnostics)
