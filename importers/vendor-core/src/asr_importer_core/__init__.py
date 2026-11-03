"""Conservative primitives shared by offline source importers."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from agent_session_record import Writer, derive_id
from agent_session_record.privacy import credential_key, credential_values, environment_secrets, redact_text
from agent_session_record.safety import read_bounded
from rfc3339_validator import validate_rfc3339

META = "org.agentsessionrecord.importers"
MAX_INT = 2**53 - 1
MAX_INPUT_BYTES = 32 * 1024 * 1024
MAX_OUTPUT_BYTES = 64 * 1024 * 1024
MAX_RECORDS = 100_000
LOSSES = ["reasoning", "usage", "tool_output", "exit_codes", "file_changes",
          "commits", "subagents", "copies", "model", "approvals", "agent_settings", "tools"]
VENDOR_CREDENTIAL_KEY = re.compile(r"^(?:api|access|auth|refresh|secret)[_-]?(?:key|token)$", re.I)
OPAQUE_KEY = re.compile(r"^(?:signature|encrypted_content|encrypted_thinking|resume_token)$", re.I)
URL_CREDENTIALS = re.compile(r"(?<=://)[^\s/@]+:[^\s/@]+@")
ASSIGNMENT = re.compile(
    r"\b((?:api|access|auth|refresh|secret)[_-]?(?:key|token)|password|session[_-]?token)"
    r"(\s*[:=]\s*)([\"']?)([^\s\"',;}]+)\3", re.I)


def loads(text: str) -> Any:
    if len(text) > MAX_INPUT_BYTES:
        raise ValueError("input_byte_limit")
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("non-finite JSON number")

    return json.loads(text, object_pairs_hook=object_pairs, parse_float=Decimal,
                      parse_constant=constant)


def native(value: Any) -> Any:
    """Keep exact native numbers as strings when a JSON number would lose them."""
    if isinstance(value, Decimal) or type(value) is int and abs(value) > MAX_INT:
        return str(value)
    if isinstance(value, dict):
        return {key: native(item) for key, item in value.items()}
    if isinstance(value, list):
        return [native(item) for item in value]
    return value


def scrub(value: Any, secrets=None) -> tuple[Any, bool]:
    if secrets is None:
        secrets = (*environment_secrets(), *credential_values(value))
    changed = False
    if isinstance(value, str):
        # Vendor envelopes often carry another JSON document as a string.
        # Inspect it too so credentials do not survive in the raw envelope.
        if value.lstrip().startswith(("{", "[")):
            try:
                parsed = loads(value)
                cleaned, nested_changed = scrub(native(parsed), secrets)
                if nested_changed:
                    return json.dumps(cleaned, ensure_ascii=False, separators=(",", ":")), True
            except (ValueError, RecursionError):
                pass
        result = ASSIGNMENT.sub(lambda m: m[1] + m[2] + "[redacted]", value)
        result = URL_CREDENTIALS.sub("[redacted]", redact_text(result, secrets, replacement="[redacted]"))
        return result, result != value
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            safe_key, key_changed = scrub(key, secrets)
            if credential_key(key) or VENDOR_CREDENTIAL_KEY.fullmatch(key) or OPAQUE_KEY.fullmatch(key):
                item, item_changed = "[redacted]", item != "[redacted]"
            else:
                item, item_changed = scrub(item, secrets)
            # Redacting two object keys must not silently overwrite either value.
            if safe_key in result:
                safe_key = "redacted-key-" + hashlib.sha256(key.encode()).hexdigest()
            result[safe_key] = item
            changed |= key_changed or item_changed
        return result, changed
    if isinstance(value, list):
        result = []
        for item in value:
            item, item_changed = scrub(item, secrets)
            result.append(item)
            changed |= item_changed
        return result, changed
    return value, False


def stamp(value: Any) -> str | None:
    if isinstance(value, str) and validate_rfc3339(value):
        return value
    return None


def millis(value: Any) -> str | None:
    if type(value) is int and 0 <= value <= MAX_INT:
        try:
            seconds, fraction = divmod(value, 1000)
            return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + f".{fraction:03d}Z"
        except (ValueError, OverflowError, OSError):
            pass
    return None


def count(value: Any) -> bool:
    return type(value) is int and 0 <= value <= MAX_INT


def usage(value: dict, *, anthropic: bool = False) -> dict:
    mapping = {"input_tokens": "inputTokens", "output_tokens": "outputTokens",
               "cache_read_input_tokens": "cacheReadTokens", "cached_input_tokens": "cacheReadTokens",
               "cache_creation_input_tokens": "cacheWriteTokens", "cache_creation_tokens": "cacheWriteTokens",
               "cache_read_tokens": "cacheReadTokens", "cache_write_input_tokens": "cacheWriteTokens",
               "reasoning_output_tokens": "reasoningTokens"}
    result = {target: value[key] for key, target in mapping.items() if key in value and count(value[key])}
    if anthropic and "inputTokens" in result:
        # Anthropic base input excludes cache reads and writes. An invalid optional
        # component cannot be treated as zero in the inclusive total.
        cache_keys = [key for key in mapping if mapping[key] in ("cacheReadTokens", "cacheWriteTokens")]
        if any(key in value and not count(value[key]) for key in cache_keys):
            result.pop("inputTokens")
        else:
            total = result["inputTokens"] + result.get("cacheReadTokens", 0) + result.get("cacheWriteTokens", 0)
            if count(total):
                result["inputTokens"] = total
            else:
                result.pop("inputTokens")
    return result


def text_parts(value: Any) -> list[dict]:
    if isinstance(value, str):
        return [{"type": "text", "text": value}]
    if isinstance(value, list):
        result = []
        for part in value:
            if isinstance(part, dict) and isinstance(part.get("text"), str) and part.get("type") in ("text", "input_text", "output_text"):
                result.append({"type": "text", "text": part["text"]})
        return result
    return []


def json_lines(data: bytes):
    """Yield a gap sentinel for each malformed or incomplete native line."""
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError("input_byte_limit")
    for position, raw in enumerate(data.splitlines(keepends=True)):
        if position >= MAX_RECORDS:
            raise ValueError("input_record_limit")
        try:
            item = loads(raw.decode("utf-8")) if raw.endswith(b"\n") else None
            if not isinstance(item, dict):
                item = None
        except (ValueError, UnicodeError):
            item = None
        yield position, item


def read_input(path: Path) -> bytes:
    return read_bounded(path, MAX_INPUT_BYTES)


class Stream:
    def __init__(self, agent: str, session: str, source: str, *, namespace: str | None = None):
        if not isinstance(session, str) or not session:
            raise ValueError("a native session ID is required")
        self.scope = json.dumps([agent, namespace, session, source])
        self.ids: set[str] = set()
        self.records: list[dict] = []
        self.retained_bytes = 0
        self.header = {"type": "session", "id": "header", "formatVersion": "0.1",
                       "agent": {"name": agent}, "sessionId": session,
                       "producer": {"name": "asr-import-" + source, "version": "0.1.0", "method": "converter", "source": source},
                       "missing": list(LOSSES)}
        if namespace:
            self.header["namespace"] = namespace
        self.ids.add("header")

    def missing(self, *names: str):
        for name in names:
            if name not in self.header["missing"]:
                self.header["missing"].append(name)

    def add(self, kind: str, *, source_id: Any = None, ts: Any = None, meta: Any = None, **fields) -> dict:
        rid = source_id if isinstance(source_id, str) and 0 < len(source_id) <= 256 and not re.search(r"[\x00-\x1f\x7f-\x9f]", source_id) else None
        collision = 0
        while rid is None or rid in self.ids:
            rid = derive_id(self.scope, kind, len(self.records), collision)
            collision += 1
        self.ids.add(rid)
        record = {"type": kind, "id": rid, **fields}
        if stamp(ts):
            record["ts"] = ts
        else:
            self.missing("timestamps")
        if meta is not None:
            record["_meta"] = {META: native(meta)}
        size = len(json.dumps(native(record), ensure_ascii=False).encode('utf-8'))
        if len(self.records) >= MAX_RECORDS or self.retained_bytes + size > MAX_OUTPUT_BYTES:
            raise ValueError("output_capacity")
        self.retained_bytes += size
        self.records.append(record)
        return record

    def gap(self, reason="unparseable", detail="A native record could not be mapped.", **kwargs):
        self.missing("history")
        return self.add("gap", reason=reason, detail=detail, **kwargs)

    def write(self, output: Path) -> None:
        secrets = (*environment_secrets(), *credential_values([self.header, *self.records]))
        # Distinct native results with a reused call ID cannot be paired safely.
        # Preserve them as unpaired records, including their native join key.
        results = Counter(r.get("callId") for r in self.records if r["type"] == "tool_result" and "callId" in r)
        for record in self.records:
            if record["type"] == "tool_result" and results[record.get("callId")] > 1:
                call_id = record.pop("callId")
                record.setdefault("_meta", {}).setdefault(META, {})["unpairedCallId"] = call_id
                self.missing("ambiguous_tool_results")
        safe_records = []
        for record in self.records:
            safe, changed = scrub(native(record), secrets)
            if changed:
                safe["truncated"] = True
                self.missing("secrets")
            safe_records.append(safe)
        header, changed = scrub(native(self.header), secrets)
        if changed:
            header["truncated"] = True
            if "secrets" not in header["missing"]:
                header["missing"].append("secrets")
        created = False
        try:
            with Writer(output, header) as writer:
                created = True
                for record in safe_records:
                    writer.append(record)
        except BaseException:
            if created:
                output.unlink(missing_ok=True)
            raise
