"""Conservative joins between independent telemetry and transcript streams."""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from importlib.resources import files
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable

from agent_session_record import Writer, derive_id
from agent_session_record.safety import read_bounded
from jsonschema import Draft202012Validator, FormatChecker

from .telemetry import Event, Number, documents, dumps, events, loads

MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_LINE_BYTES = 16 * 1024 * 1024
MAX_RECORDS = 100_000


META = "org.agentsessionrecord.telemetry-approvals"
PRODUCER = {"name": "asr-telemetry-approvals", "version": "0.1.0", "method": "converter",
            "source": "agent-session+opentelemetry-logs"}
SCHEMA = Draft202012Validator(json.loads(files("agent_session_record").joinpath("_schemas/agent-session.schema.json").read_text()), format_checker=FormatChecker())
SAFE_NATIVE = {"decision", "source", "reasonType", "reason_type", "classifier_verdict",
               "grant_scope", "decision_source", "category", "rule_source", "reason_code",
               "event.name", "event.timestamp", "event.sequence", "tool_use_id", "call_id",
               "tool_name", "subject", "app.version"}
from agent_session_record.privacy import TOKEN as SECRET, credential_values, redact_text, environment_secrets


def native_evidence(attrs: dict) -> dict:
    def normalize(value):
        if isinstance(value, Number) or type(value) is int and abs(value) > 2**53 - 1:
            return str(value)
        if isinstance(value, dict):
            return {k: normalize(v) for k, v in value.items()}
        if isinstance(value, list):
            return [normalize(v) for v in value]
        return value
    return {k: normalize(v) for k, v in attrs.items() if k in SAFE_NATIVE}


def lines(path: Path):
    size = 0
    with path.open("rb") as stream:
        for position, raw in enumerate(iter(lambda: stream.readline(MAX_LINE_BYTES + 1), b'')):
            size += len(raw)
            if len(raw) > MAX_LINE_BYTES or size > MAX_INPUT_BYTES or position >= MAX_RECORDS:
                raise ValueError('input_capacity')
            try:
                record = loads(raw.decode("utf-8")) if raw.endswith(b"\n") else None
                if not isinstance(record, dict):
                    record = None
            except (UnicodeError, ValueError):
                record = None
            yield position, raw, record


def timestamp(event: Event) -> str | None:
    recorded = event.attrs.get("event.timestamp")
    if isinstance(recorded, str):
        try:
            value = datetime.fromisoformat(recorded.replace("Z", "+00:00"))
            if value.tzinfo is not None:
                return recorded
        except ValueError:
            pass
    # OTLP nanoseconds are source event time. observedTimeUnixNano is not used.
    nano = event.timestamp
    if isinstance(nano, (str, int)) and re.fullmatch(r"[0-9]+", str(nano)) and int(nano) > 0:
        try:
            seconds, fraction = divmod(int(nano), 10**9)
            base = datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
            return base + ("." + f"{fraction:09d}" if fraction else "") + "Z"
        except (ValueError, OSError, OverflowError):
            pass
    return None


def reviewed_codex(event: Event, header: dict) -> bool:
    version = event.attrs.get("app.version", event.resource.get("service.version", header["agent"].get("version")))
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", str(version))
    return bool(match and (0, 144, 3) <= tuple(map(int, match.groups())) <= (0, 163, 0))


def decode(event: Event, header: dict, safety: Event | None = None) -> dict | None:
    attrs = event.attrs
    value, source = attrs.get("decision"), attrs.get("source")
    result: dict[str, Any] = {}
    if event.name == "codex.tool_decision":
        if not reviewed_codex(event, header):
            return None
        mapping = {"approved": ("approved", "once"), "approved_for_session": ("approved", "session"),
                   "approved_with_amendment": ("approved", "always"),
                   "approved_mcp_policy_amendment": ("approved", "always"),
                   "approved_with_network_policy_allow": ("approved", "always"),
                   "denied_with_network_policy_deny": ("denied", None),
                   "denied": ("denied", None), "abort": ("denied", None), "timed_out": ("cancelled", None)}
        if not isinstance(value, str) or value not in mapping:
            return None
        result["decision"], scope = mapping[value]
        if scope:
            result["scope"] = scope
        by = {"User": "user", "Config": "policy", "AutomatedReviewer": "classifier"}.get(source)
        if by and not (result["decision"] == "cancelled" and by == "user"):
            result["by"] = by
    else:
        if source == "user_abort" and value == "reject":
            result["decision"] = "cancelled"
        elif value in ("accept", "reject"):
            result["decision"] = {"accept": "approved", "reject": "denied"}[value]
        else:
            return None
        reason = attrs.get("reasonType", attrs.get("reason_type"))
        if safety:
            reason = safety.attrs.get("reason_type", reason)
        if result["decision"] == "cancelled":
            pass
        elif reason == "mode":
            result["by"] = "mode"
        elif source == "hook":
            result["by"] = "hook"
        elif reason == "classifier" or attrs.get("classifier_verdict") in ("allow", "block", "no_verdict", "unavailable"):
            result["by"] = "classifier"
        elif source == "config":
            result["by"] = "policy"
        elif source == "user_reject":
            result["by"] = "user"
        if result["decision"] == "approved":
            if source == "user_permanent":
                result["scope"] = "always"
            elif safety and safety.attrs.get("grant_scope") in ("once", "session"):
                result["scope"] = safety.attrs["grant_scope"]
    if isinstance(attrs.get("subject"), str):
        result["subject"] = attrs["subject"]
    if recorded := timestamp(event):
        result["ts"] = recorded
    # Keep decision evidence only. Exported prompts, arguments and account data
    # are irrelevant to this join and can contain credentials.
    native = native_evidence(attrs)
    if any(SECRET.search(dumps(v)) for v in native.values()):
        return None
    result["native"] = native
    if safety:
        evidence = native_evidence(safety.attrs)
        if not SECRET.search(dumps(evidence)):
            result["_meta"] = {META: {"safety": evidence}}
    return result


def matches(event: Event, header: dict) -> bool:
    attrs = event.attrs
    if header["agent"]["name"] == "claude-code" and event.name.startswith("claude_code."):
        identity = attrs.get("agent_id") or attrs.get("session.id")
    elif header["agent"]["name"] == "codex" and event.name == "codex.tool_decision":
        identity = attrs.get("conversation.id")
    else:
        return False
    return identity == header["sessionId"] and attrs.get("session.namespace") == header.get("namespace")


def equivalent(existing: dict, incoming: dict) -> bool:
    if existing.get("callId") != incoming.get("callId") or existing.get("decision") != incoming["decision"]:
        return False
    if existing.get("subject") != incoming.get("subject"):
        return False
    if "person" in existing and incoming.get("by") not in (None, "user"):
        return False
    a, b = existing.get("native"), incoming["native"]
    if not isinstance(a, dict) or a.get("source") != b.get("source") or a.get("decision") != b.get("decision"):
        return False
    # A timestamp, when supplied on both observations, distinguishes repeats.
    if existing.get("ts") and incoming.get("ts") and existing["ts"] != incoming["ts"]:
        return False
    if "scope" in existing and "scope" in incoming and existing["scope"] != incoming["scope"]:
        return False
    deciders = {existing.get("by"), incoming.get("by")}
    return None in deciders or len(deciders) == 1 or deciders in ({"policy", "mode"}, {"policy", "classifier"})


def import_approvals(source: str | Path, telemetry: Iterable[str | Path], output: str | Path) -> dict[str, int | bool]:
    """Create a new file. Inputs are never modified and output is exclusive."""
    source, output = Path(source), Path(output)
    if output.exists() or source.resolve() == output.resolve():
        raise FileExistsError("output must be a new file")
    digest = hashlib.sha256()
    ids: set[str] = set()
    calls: Counter = Counter()
    results: dict[str, int] = {}
    existing: dict[int, dict] = {}
    corrupt = 0
    invalid_positions: set[int] = set()
    inherited_gap = False
    losses: set[str] = set()
    model_without_identity = False
    for position, raw, record in lines(source):
        digest.update(raw)
        if SECRET.search(raw.decode("utf-8", errors="replace")):
            raise ValueError("source contains a recognized credential. Redact it before importing")
        if record is not None and (credential_values(record) or
                redact_text(json.dumps(record), environment_secrets()) != json.dumps(record)):
            raise ValueError("source contains a recognized credential. Redact it before importing")
        if record is not None and not SCHEMA.is_valid(json.loads(raw)):
            record = None
        if position == 0:
            if record is None or record.get("type") != "session" or record.get("formatVersion") != "0.1":
                raise ValueError("source needs a complete ASR 0.1 session header")
            header = deepcopy(record)
        elif record and record.get("type") == "session":
            raise ValueError("source has more than one session")
        if record is None:
            corrupt += 1
            invalid_positions.add(position)
            continue
        if not isinstance(record.get("id"), str) or record["id"] in ids:
            raise ValueError("source needs unique string record IDs")
        ids.add(record["id"])
        if record["type"] == "tool_call":
            calls[record["callId"]] += 1
        if record["type"] == "tool_result" and "callId" in record:
            if record["callId"] in results:
                raise ValueError("source has duplicate tool results")
            results[record["callId"]] = position
        if record["type"] == "approval":
            existing[position] = record
        if record["type"] == "gap":
            inherited_gap = True
        if record["type"] in ("session", "session_info"):
            losses.update(record.get("missing", []))
        if record["type"] == "inference" and "model" not in record:
            model_without_identity = True
    if not ids:
        raise ValueError("empty source")
    if model_without_identity and "model" not in losses:
        raise ValueError("source inference has no model or model loss declaration")
    if header.get("parent", {}).get("copiedThrough") and header["parent"]["copiedThrough"] not in ids - {header["id"]}:
        raise ValueError("source copied prefix has no valid boundary")
    selected: list[Event] = []
    telemetry_bytes = 0
    for path in telemetry:
        try:
            data = read_bounded(path, 32 * 1024 * 1024)
            telemetry_bytes += len(data)
            if telemetry_bytes > 32 * 1024 * 1024:
                raise ValueError('input_capacity')
            for document in documents(data.decode('utf-8')):
                selected.extend(event for event in events(document) if matches(event, header))
                if len(selected) > MAX_RECORDS:
                    raise ValueError('event_capacity')
        except (ValueError, KeyError, TypeError, RecursionError) as error:
            raise ValueError("invalid telemetry file") from error
    decisions = [e for e in selected if e.name != "claude_code.safety_event"]
    call_id = lambda e: e.attrs.get("call_id" if e.name.startswith("codex.") else "tool_use_id")
    counts = Counter(call_id(e) for e in decisions)
    safety_events: dict[str, list[Event]] = defaultdict(list)
    for event in selected:
        if event.name == "claude_code.safety_event":
            safety_events[call_id(event)].append(event)
    insert: dict[int, list[dict]] = defaultdict(list)
    updates: dict[int, dict] = {}
    consumed: set[int] = set()
    covered: set[str] = set()
    unpositioned = []
    occurrences: Counter = Counter()
    repeated: set[str] = set()
    seen = {r.get("_meta", {}).get(META, {}).get("eventKey") for r in existing.values()}
    inserted = reconciled = 0
    for event in decisions:
        call = call_id(event)
        safety = None
        candidates = [s for s in safety_events.get(call, []) if s.attrs.get("decision") == event.attrs.get("decision")
                      and s.attrs.get("decision_source", event.attrs.get("source")) == event.attrs.get("source")]
        if counts[call] == 1 and len(candidates) == 1:
            safety = candidates[0]
        record = decode(event, header, safety)
        fingerprint = hashlib.sha256(dumps([event.name, event.attrs, event.resource, event.timestamp]).encode()).hexdigest()
        # A sequence plus event time identifies a transported observation. With
        # no such identity, identical observations can be distinct decisions.
        explicit = "event.sequence" in event.attrs and timestamp(event) is not None
        if explicit and fingerprint in repeated:
            continue
        repeated.add(fingerprint)
        ordinal = occurrences[fingerprint]
        occurrences[fingerprint] += 1
        key = hashlib.sha256(f"{fingerprint}:{ordinal}".encode()).hexdigest()
        if record is None or not isinstance(call, str) or calls[call] != 1 or call not in results:
            snapshot = {"event": event.name, "reason": "unknown-decision" if record is None else "no-unique-call-result"}
            if record is not None:
                snapshot["approval"] = record
                if isinstance(call, str):
                    snapshot["approval"]["callId"] = call
            # Unknown decisions retain only credential-free decision evidence.
            elif not SECRET.search(dumps(native_evidence(event.attrs))):
                snapshot["native"] = native_evidence(event.attrs)
            unpositioned.append(snapshot)
            continue
        record["callId"] = call
        covered.add(call)
        if key in seen:
            continue
        match = next((pos for pos, old in existing.items() if pos not in consumed and equivalent(old, record)), None)
        if match is not None:
            consumed.add(match)
            merged = deepcopy(existing[match])
            for field in ("by", "scope", "ts"):
                if field in record and field not in merged:
                    merged[field] = record[field]
            if merged.get("by") == "policy" and record.get("by") in ("mode", "classifier"):
                merged["by"] = record["by"]
            merged.setdefault("_meta", {}).setdefault(META, {}).update({"eventKey": key, "telemetry": record["native"]})
            updates[match] = merged
            reconciled += 1
        else:
            collision = 0
            while (rid := derive_id(key, "approval", 0, collision)) in ids:
                collision += 1
            ids.add(rid)
            record.update({"type": "approval", "id": rid})
            record.setdefault("_meta", {}).setdefault(META, {})["eventKey"] = key
            insert[results[call]].append(record)
            inserted += 1
    prior_unpositioned = header.get("_meta", {}).get(META, {}).get("unpositioned", [])
    complete = bool(calls) and not corrupt and not inherited_gap and not prior_unpositioned and not unpositioned and all(count == 1 and call in covered for call, count in calls.items())
    complete = complete and all(call in calls for call in results)
    header["producer"] = PRODUCER.copy()
    header["derivedFrom"] = {"sha256": digest.hexdigest()}
    if "approvals" not in header.get("missing", []):
        header.setdefault("missing", []).append("approvals")
    if corrupt and "records" not in header["missing"]:
        header["missing"].append("records")
    metadata = header.setdefault("_meta", {}).setdefault(META, {})
    if unpositioned:
        metadata.setdefault("unpositioned", []).extend(unpositioned)
    metadata["coverage"] = {"calls": sum(calls.values()), "coveredCalls": len(covered), "complete": complete}
    # The Python writer checks all new approval and gap records. Existing lines
    # pass through byte-for-byte, including unfamiliar fields and exact numbers.
    # A separate fragment avoids converting inherited numbers through floats.
    with tempfile.TemporaryDirectory(prefix="asr-approvals-") as temporary:
        fragment = Path(temporary) / "records.jsonl"
        minimal = {k: header[k] for k in ("type", "id", "formatVersion", "sessionId", "producer")}
        minimal["agent"] = {"name": header["agent"]["name"]}
        gaps = {}
        with Writer(fragment, minimal) as writer:
            for records in insert.values():
                for record in records:
                    writer.append(record)
            for position in sorted(invalid_positions):
                collision = 0
                while (rid := derive_id(digest.hexdigest(), "gap", position, collision)) in ids:
                    collision += 1
                ids.add(rid)
                gaps[position] = {"type": "gap", "id": rid, "reason": "unparseable", "count": 1,
                                  "detail": "An invalid or incomplete source ASR line was not imported."}
                writer.append(gaps[position])
        created = False
        try:
            with os.fdopen(os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as destination:
                created = True
                destination.write((dumps(header) + "\n").encode())
                emitted_digest = hashlib.sha256()
                for position, raw, record in lines(source):
                    emitted_digest.update(raw)
                    if position == 0:
                        continue
                    for approval in insert.get(position, []):
                        destination.write((dumps(approval) + "\n").encode())
                    if position in invalid_positions:
                        raw = (dumps(gaps[position]) + "\n").encode()
                    elif position in updates:
                        raw = (dumps(updates[position]) + "\n").encode()
                    destination.write(raw)
                if emitted_digest.digest() != digest.digest():
                    raise ValueError("source changed during import")
        except BaseException:
            if created:
                output.unlink(missing_ok=True)
            raise
    return {"calls": sum(calls.values()), "coveredCalls": len(covered), "inserted": inserted,
            "reconciled": reconciled, "unpositioned": len(unpositioned), "gaps": corrupt, "complete": complete}
