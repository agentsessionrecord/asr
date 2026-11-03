"""Recovery, identity, conservative joins and copy credit for ASR 0.1."""

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from agent_session_record import encode_component, session_reference

from .jsonio import loads
from .validation import valid_record

CORE = {"session", "session_info", "message", "tool_call", "tool_result", "approval",
        "file_change", "vcs", "inference", "gap"}


MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_LINE_BYTES = 16 * 1024 * 1024
MAX_RECORDS = 100_000


def component(value):
    return encode_component(value)


def session_ref(header):
    return session_reference(header["agent"]["name"], header["sessionId"], namespace=header.get("namespace"))


def stable_id(reference, size=16):
    digest = sha256(reference.encode()).hexdigest()[:size * 2]
    suffix = 0
    while not int(digest, 16):
        suffix += 1
        digest = sha256(f"{reference}#{suffix}".encode()).hexdigest()[:size * 2]
    return digest


def _strings(value):
    return [x for x in value if isinstance(x, str)] if isinstance(value, list) else []


def _updates(settings, supplied):
    if any(k in supplied and supplied.get(k) != settings.get(k)
           for k in ("mode", "approval", "sandbox")) and "asks" not in supplied:
        settings.pop("asks", None)
    for key, value in supplied.items():
        if value is None:
            settings.pop(key, None)
        elif key == "modelSettings" and isinstance(value, dict):
            nested = settings.setdefault(key, {})
            for name, item in value.items():
                if item is None:
                    nested.pop(name, None)
                else:
                    nested[name] = deepcopy(item)
        else:
            settings[key] = deepcopy(value)


@dataclass
class Session:
    header: dict
    records: list
    digest: str
    diagnostics: list = field(default_factory=list)
    lines: dict = field(default_factory=dict)

    def __post_init__(self):
        self.ref = session_ref(self.header)
        self.by_id = {r["id"]: r for r in self.records}
        self.calls = defaultdict(list)
        self.results = defaultdict(list)
        self.copied = set()
        self.settings = {}
        self.tools = {}
        self.missing = set(_strings(self.header.get("missing")))
        self.latest = deepcopy(self.header)
        parent = self.header.get("parent", {})
        boundary = parent.get("copiedThrough")
        in_prefix = boundary is not None
        if in_prefix and boundary not in self.by_id:
            self.diagnostics.append({"code": "unresolved_copy_boundary"})
        current, offered = {}, None
        for record in self.records:
            rid = record["id"]
            if in_prefix or "copiedFrom" in record:
                self.copied.add(rid)
            if rid == boundary:
                in_prefix = False
            kind = record["type"]
            if kind == "tool_call" and isinstance(record.get("callId"), str):
                self.calls[record["callId"]].append(record)
            if kind == "tool_result" and isinstance(record.get("callId"), str):
                self.results[record["callId"]].append(record)
            if kind == "session_info":
                self.missing.update(_strings(record.get("missing")))
                if isinstance(record.get("agentSettings"), dict):
                    _updates(current, record["agentSettings"])
                if "tools" in record:
                    offered = deepcopy(record["tools"])
                for key in ("title", "endedAt", "usage", "cost"):
                    if key in record:
                        self.latest[key] = deepcopy(record[key])
                if "repos" in record:
                    self.latest.setdefault("repos", []).extend(deepcopy(record["repos"]))
            self.settings[rid] = deepcopy(current)
            self.tools[rid] = deepcopy(offered)

    def cite(self, record):
        return self.ref + "#" + component(record["id"])

    def original(self, record):
        return record["id"] not in self.copied

    def call(self, call_id):
        calls = self.calls.get(call_id, [])
        return calls[0] if len(calls) == 1 else None

    def result(self, call):
        results = self.results.get(call.get("callId"), [])
        return results[0] if self.call(call.get("callId")) is call and len(results) == 1 else None

    def effective_input(self, call):
        result = self.result(call)
        for record in (result, call):
            if record is not None:
                for key in ("input", "inputText"):
                    if key in record:
                        return {key: deepcopy(record[key])}
        return {}

    def accounting(self):
        figures, costs = {}, {}
        calls = unknown_usage = unknown_cost = 0
        for record in self.records:
            if record["type"] != "inference" or not self.original(record):
                continue
            calls += 1
            if "usage" not in record:
                unknown_usage += 1
            for key, value in record.get("usage", {}).items():
                if key in {"inputTokens", "outputTokens", "cacheReadTokens", "cacheWriteTokens", "reasoningTokens"}:
                    figures[key] = figures.get(key, 0) + value
            if "cost" not in record:
                unknown_cost += 1
            else:
                cost = record["cost"]
                model = record.get("model", {})
                key = (model.get("id"), model.get("requested"), model.get("provider"), cost["currency"])
                costs[key] = costs.get(key, 0) + cost["amount"]
        return {"inferences": calls, "known_usage_sums": figures,
                "usage_fields_are_partial": True, "calls_without_usage": unknown_usage,
                "calls_without_cost": unknown_cost,
                "cost_by_model_currency": [dict(zip(("served", "requested", "provider", "currency"), key), amount=value)
                                           for key, value in costs.items()]}


def _lines(path, diagnostics, digest=None):
    size = 0
    with Path(path).open("rb") as stream:
        for number, raw in enumerate(iter(lambda: stream.readline(MAX_LINE_BYTES + 1), b''), 1):
            size += len(raw)
            if len(raw) > MAX_LINE_BYTES or size > MAX_INPUT_BYTES or number > MAX_RECORDS:
                raise ValueError('input_capacity')
            if digest is not None:
                digest.update(raw)
            if not raw.endswith(b"\n"):
                diagnostics.append({"line": number, "code": "incomplete_tail"})
                break
            try:
                value = loads(raw.decode("utf-8"))
                if not isinstance(value, dict):
                    raise ValueError("not_object")
            except (ValueError, UnicodeError, RecursionError):
                diagnostics.append({"line": number, "code": "malformed_line"})
                continue
            yield number, value


def read_session(path):
    diagnostics, records, positions = [], [], {}
    header = None
    seen = set()
    digest = sha256()
    for line, record in _lines(path, diagnostics, digest):
        kind, rid = record.get("type"), record.get("id")
        if not isinstance(kind, str) or not isinstance(rid, str) or not rid or len(rid) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in rid):
            diagnostics.append({"line": line, "code": "invalid_envelope"})
            continue
        if line == 1:
            if kind != "session" or record.get("formatVersion") != "0.1":
                raise ValueError("unsupported_or_missing_header")
            if not valid_record(record):
                raise ValueError("invalid_session_identity")
            agent = record.get("agent")
            if not isinstance(agent, dict) or not isinstance(agent.get("name"), str) or not agent["name"] or not isinstance(record.get("sessionId"), str) or not record["sessionId"]:
                raise ValueError("invalid_session_identity")
            if "namespace" in record and (not isinstance(record["namespace"], str) or not record["namespace"]):
                raise ValueError("invalid_session_identity")
            header = record
        elif kind == "session":
            diagnostics.append({"line": line, "code": "extra_session"})
            continue
        elif rid in seen:
            diagnostics.append({"line": line, "code": "duplicate_record_id"})
            continue
        elif not valid_record(record):
            diagnostics.append({"line": line, "code": "invalid_record_shape"})
            continue
        else:
            records.append(record)
        seen.add(rid)
        positions[rid] = line
    if header is None:
        raise ValueError("missing_header")
    return Session(header, records, digest.hexdigest(), diagnostics, positions)


def load_sessions(paths):
    sessions = {}
    for path in paths:
        session = read_session(path)
        if session.ref in sessions and sessions[session.ref].digest != session.digest:
            raise ValueError("conflicting_session_exports")
        sessions.setdefault(session.ref, session)
    return list(sessions.values())


def read_annotations(paths):
    active, diagnostics = [], []
    for index, path in enumerate(paths):
        seen, current = set(), {}
        for line, item in _lines(path, diagnostics):
            rid = item.get("id")
            if not valid_record(item, annotation=True):
                diagnostics.append({"file": index, "line": line, "code": "invalid_annotation"})
                continue
            supersedes = item.get("supersedes")
            if rid in seen or (supersedes is not None and supersedes not in seen):
                diagnostics.append({"file": index, "line": line, "code": "invalid_annotation_correction"})
                continue
            seen.add(rid)
            current.pop(supersedes, None)
            current[rid] = item
        active.extend(current.values())
    return active, diagnostics
