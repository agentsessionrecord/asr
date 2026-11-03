"""Map established ASR facts to the revisions pinned by guides/otel.md."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import re

from .reader import Session, exact_json, record_ref, telemetry_id

VERSION = "0.1.0"
GENAI_REVISION = "72e0d0a097db3ba31ba3f33d0519401a044f6e23"
CORE_REVISION = "debfc1c62dcaf49eece43e3ee1d56a92b837a7e2"
KNOWN = {"session", "session_info", "message", "inference", "tool_call", "tool_result",
         "approval", "gap", "file_change", "vcs"}
TIMESTAMP = re.compile(r"(\d{4}-\d\d-\d\d)[Tt](\d\d:\d\d:\d\d)(?:\.(\d+))?([Zz]|[+-]\d\d:\d\d)\Z")
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def obj(value):
    return value if isinstance(value, dict) else {}


def strings(value):
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def timestamp(value):
    if not isinstance(value, str) or not (match := TIMESTAMP.fullmatch(value)):
        return None
    date, time, fraction, offset = match.groups()
    if fraction and len(fraction) > 9:
        return None
    try:
        moment = datetime.fromisoformat(date + "T" + time + ("+00:00" if offset.lower() == "z" else offset))
        delta = moment - EPOCH
        nanos = (delta.days * 86400 + delta.seconds) * 1_000_000_000
        nanos += int((fraction or "").ljust(9, "0"))
        return nanos if 0 < nanos < 2**64 else None
    except ValueError:
        return None


def duration(value):
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        return None
    nanos = Decimal(value) * 1_000_000
    if nanos < 0 or nanos != nanos.to_integral_value() or nanos >= 2**64:
        return None
    return int(nanos)


def any_value(value):
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int) and -(2**63) <= value < 2**63:
        return {"intValue": str(value)}
    if isinstance(value, str):
        return {"stringValue": value}
    if isinstance(value, list):
        return {"arrayValue": {"values": [any_value(v) for v in value]}}
    # Custom structured values stay exact JSON strings. Decimal numbers never round.
    return {"stringValue": exact_json(value)}


def attributes(values):
    return [{"key": key, "value": any_value(value)} for key, value in values.items()]


def numeric_attribute(values, key, value, integer=False):
    if integer:
        if type(value) is int and 0 <= value < 2**63:
            values[key] = value
    elif not isinstance(value, bool) and isinstance(value, (int, Decimal)):
        # OTLP double fields are necessarily IEEE 754. The exact ASR value also stays custom.
        converted = float(value)
        if abs(converted) < float("inf"):
            values[key] = converted


def wire_attributes(values):
    return [{"key": k, "value": {"doubleValue": v} if isinstance(v, float) else any_value(v)}
            for k, v in values.items()]


def merge_attributes(item, values):
    replaced = set(values)
    item["attributes"] = [a for a in item["attributes"] if a["key"] not in replaced] + attributes(values)


def safe_content(value):
    if isinstance(value, list):
        return [safe_content(v) for v in value]
    if isinstance(value, dict):
        if value.get("type") == "reasoning" and value.get("visibility") == "encrypted":
            return {k: v for k, v in value.items() if k in {"type", "visibility", "author", "origin"}}
        return {k: safe_content(v) for k, v in value.items()}
    return value


CONTRACT_FIELDS = {"producer", "inferenceTimestamp", "toolCallTimestamp", "toolResultTimestamp",
                   "basis", "inferenceIdIsResponse", "responseIdMetaPath", "serviceTier",
                   "reasoningEffortIsRequest"}


def validate_contracts(config):
    if not isinstance(config, dict) or set(config) != {"producers"} or not isinstance(config["producers"], list):
        raise ValueError("invalid_contracts")
    seen = set()
    for contract in config["producers"]:
        if not isinstance(contract, dict) or set(contract) - CONTRACT_FIELDS:
            raise ValueError("invalid_contract")
        producer = contract.get("producer")
        if (not isinstance(producer, dict) or set(producer) - {"name", "version", "method", "source"}
                or any(not isinstance(producer.get(k), str) or not producer[k]
                       for k in ("name", "version", "method"))):
            raise ValueError("invalid_contract_producer")
        key = exact_json(dict(sorted(producer.items())))
        if key in seen:
            raise ValueError("duplicate_contract")
        seen.add(key)
        for name, allowed in {"inferenceTimestamp": {"start", "end", "unknown"},
                              "toolCallTimestamp": {"start", "unknown"},
                              "toolResultTimestamp": {"end", "unknown"},
                              "basis": {"source", "receipt"},
                              "serviceTier": {"request", "response", "unknown"}}.items():
            if name in contract and (not isinstance(contract[name], str) or contract[name] not in allowed):
                raise ValueError("invalid_contract_value")
        for name in ("inferenceIdIsResponse", "reasoningEffortIsRequest"):
            if name in contract and not isinstance(contract[name], bool):
                raise ValueError("invalid_contract_value")
        if "responseIdMetaPath" in contract and (not isinstance(contract["responseIdMetaPath"], list)
                or not contract["responseIdMetaPath"]
                or any(not isinstance(k, str) or not k for k in contract["responseIdMetaPath"])):
            raise ValueError("invalid_contract_value")
    return config["producers"]


@dataclass
class Export:
    traces: dict
    logs: dict
    report: dict


class SessionExport:
    def __init__(self, session, contract, include_content, include_identity, user_name_kind):
        self.session = session
        self.contract = contract
        self.include_content = include_content
        self.include_identity = include_identity
        self.reference = session.reference
        self.trace_id = telemetry_id(self.reference, 32)
        self.spans = {}
        self.logs = []
        self.diagnostics = list(session.diagnostics)
        self.calls, self.results = defaultdict(list), defaultdict(list)
        self.by_id = {e.data["id"]: e for e in session.entries}
        self.identity = {}
        if include_identity:
            user = obj(session.header.get("user"))
            for key in ("id", "email"):
                if key in user:
                    self.identity["user." + key] = user[key]
            if "name" in user:
                target = {"short": "user.name", "full": "user.full_name"}.get(user_name_kind, "asr.user.name")
                self.identity[target] = user["name"]
            if "source" in user:
                self.identity["asr.user.source"] = user["source"]
        for entry in session.entries:
            record = entry.data
            if record["type"] == "tool_call" and isinstance(record.get("callId"), str):
                self.calls[record["callId"]].append(entry)
            if record["type"] == "tool_result" and isinstance(record.get("callId"), str):
                self.results[record["callId"]].append(entry)

    def diagnostic(self, entry, code):
        self.diagnostics.append({"line": entry.line, "code": code})

    def unique_call(self, call_id):
        if not isinstance(call_id, str):
            return None
        matches = self.calls.get(call_id, [])
        return matches[0] if len(matches) == 1 else None

    def paired_result(self, entry):
        call_id = entry.data.get("callId")
        results = self.results.get(call_id, [])
        return results[0] if self.unique_call(call_id) is entry and len(results) == 1 else None

    def base(self, entry):
        record = entry.data
        values = {"gen_ai.conversation.id": self.session.header["sessionId"],
                  "gen_ai.agent.name": self.session.header["agent"]["name"],
                  "asr.session_ref": self.reference, "asr.record_id": record["id"],
                  "asr.record.type": record["type"], "asr.record.index": entry.line - 1,
                  "asr.copied": entry.copied, **self.identity}
        if "version" in self.session.header["agent"]:
            values["gen_ai.agent.version"] = self.session.header["agent"]["version"]
        for key in ("turnId", "inferenceId", "truncated", "copiedFrom", "ts"):
            if key in record:
                values["asr." + key] = record[key]
        return values

    def metadata(self, entry):
        record = entry.data
        values = self.base(entry)
        # These are descriptive facts, never text interpreted as actions or blame.
        fields = {"message": ("role", "author", "origin", "phase", "status", "from"),
                  "tool_call": ("callId", "name", "kind", "requestedBy", "parentCallId"),
                  "tool_result": ("callId", "status", "durationMs"),
                  "approval": ("callId", "decision", "by", "scope"),
                  "gap": ("reason", "count"),
                  "file_change": ("path", "oldPath", "op", "status", "callId", "actor"),
                  "vcs": ("action", "status", "evidence", "commit", "commitPrefix", "callId", "actor"),
                  "session": ("parent", "missing", "startedAt", "endedAt", "derivedFrom"),
                  "session_info": ("missing", "endedAt", "agentSettings"),
                  "inference": ("model", "settings", "stopReason", "durationMs")}
        for key in fields.get(record["type"], ()):
            if key in record:
                values["asr." + key] = record[key]
        if record["type"] in {"tool_call", "tool_result"} and "subagent" in record:
            child = obj(record["subagent"]).get("session")
            if isinstance(child, str):
                values["asr.subagent.session"] = child
        return values

    def inference_attributes(self, entry, values):
        record = entry.data
        model = obj(record.get("model"))
        for native, standard in (("provider", "provider.name"), ("requested", "request.model"), ("id", "response.model")):
            if isinstance(model.get(native), str):
                values["gen_ai." + standard] = model[native]
        if self.contract.get("inferenceIdIsResponse"):
            values["gen_ai.response.id"] = record["id"]
        response = record.get("_meta")
        for key in self.contract.get("responseIdMetaPath", []):
            response = obj(response).get(key)
        if self.contract.get("responseIdMetaPath") and isinstance(response, str):
            values["gen_ai.response.id"] = response
        if isinstance(record.get("stopReason"), str):
            values["gen_ai.response.finish_reasons"] = [record["stopReason"]]
        settings = obj(record.get("settings"))
        numeric_attribute(values, "gen_ai.request.max_tokens", settings.get("maxOutputTokens"), integer=True)
        numeric_attribute(values, "gen_ai.request.temperature", settings.get("temperature"))
        if self.contract.get("reasoningEffortIsRequest") and isinstance(settings.get("reasoningEffort"), str):
            values["gen_ai.request.reasoning.level"] = settings["reasoningEffort"]
        tier = self.contract.get("serviceTier")
        if model.get("provider") == "openai" and tier in {"request", "response"} and "serviceTier" in settings:
            values[f"openai.{tier}.service_tier"] = settings["serviceTier"]
        if not entry.copied:
            usage = obj(record.get("usage"))
            for native, standard in (("inputTokens", "input_tokens"), ("outputTokens", "output_tokens"),
                                     ("cacheReadTokens", "cache_read.input_tokens"),
                                     ("cacheWriteTokens", "cache_write.input_tokens"),
                                     ("reasoningTokens", "reasoning.output_tokens")):
                numeric_attribute(values, "gen_ai.usage." + standard, usage.get(native), integer=True)
            if "cost" in record:
                values["asr.cost"] = record["cost"]

    def operation_interval(self, entry):
        record = entry.data
        if record["type"] == "inference":
            point, elapsed = timestamp(record.get("ts")), duration(record.get("durationMs"))
            meaning = self.contract.get("inferenceTimestamp")
            if point is not None and elapsed is not None:
                if meaning == "start":
                    return point, point + elapsed
                if meaning == "end":
                    return point - elapsed, point
        if record["type"] == "tool_call":
            result = self.paired_result(entry)
            if result and not result.copied and self.contract.get("toolCallTimestamp") == "start":
                start = timestamp(record.get("ts"))
                if start is None:
                    return None
                if self.contract.get("toolResultTimestamp") == "end" and "ts" in result.data:
                    end = timestamp(result.data["ts"])
                    return (start, end) if end is not None else None
                elapsed = duration(result.data.get("durationMs"))
                if elapsed is not None:
                    return start, start + elapsed
        return None

    def make_span(self, entry, interval, operation, basis):
        start, end = interval
        if not (0 < start <= end < 2**64):
            self.diagnostic(entry, "invalid_interval")
            return
        values = self.metadata(entry)
        values.update({"gen_ai.operation.name": operation, "asr.timing.basis": basis})
        record = entry.data
        outcome = None
        if record["type"] == "inference":
            self.inference_attributes(entry, values)
            outcome = record
        elif record["type"] == "tool_call":
            values["gen_ai.tool.call.id"] = record["callId"]
            if "name" in record:
                values["gen_ai.tool.name"] = record["name"]
            result = self.paired_result(entry)
            outcome = result.data
            values["asr.result.record_id"] = outcome["id"]
            values["asr.result.status"] = outcome.get("status", "unknown")
            if self.include_content:
                effective = outcome if "input" in outcome or "inputText" in outcome else record
                for key in ("input", "inputText"):
                    if key in effective:
                        values["asr.tool.effective_" + key] = safe_content(effective[key])
        span = {"traceId": self.trace_id, "spanId": telemetry_id(record_ref(self.reference, record["id"]), 16),
                "name": operation, "kind": 3 if operation == "chat" else 1,
                "startTimeUnixNano": str(start), "endTimeUnixNano": str(end),
                "attributes": wire_attributes(values)}
        if outcome is not None and ("error" in outcome or outcome.get("status") == "failed"):
            span["status"] = {"code": 2}
            code = obj(outcome.get("error")).get("code")
            if isinstance(code, (str, int, Decimal)) and not isinstance(code, bool):
                span["attributes"].extend(attributes({"error.type": str(code)}))
        self.spans[record["id"]] = span

    def build_spans(self):
        default_basis = "receipt" if self.session.header["producer"]["method"] == "recorder" else "source"
        for entry in self.session.entries[1:]:
            if entry.copied or entry.data["type"] not in {"inference", "tool_call"}:
                continue
            interval = self.operation_interval(entry)
            if interval is None:
                self.diagnostic(entry, "span_timing_unavailable")
            else:
                operation = "chat" if entry.data["type"] == "inference" else "execute_tool"
                self.make_span(entry, interval, operation, self.contract.get("basis", default_basis))
        header_entry = self.session.entries[0]
        if header_entry.copied:
            return
        start, end = timestamp(self.session.header.get("startedAt")), self.session.header.get("endedAt")
        for entry in self.session.entries[1:]:
            if not entry.copied and entry.data["type"] == "session_info" and "endedAt" in entry.data:
                end = entry.data["endedAt"]
        end = timestamp(end)
        if start is None or end is None:
            self.diagnostic(header_entry, "session_timing_unavailable")
            return
        points = [timestamp(e.data.get("ts")) for e in self.session.entries if not e.copied]
        points += [int(s[k]) for s in self.spans.values() for k in ("startTimeUnixNano", "endTimeUnixNano")]
        if start > end or any(p is not None and not start <= p <= end for p in points):
            self.diagnostic(header_entry, "session_interval_excludes_activity")
            return
        basis = "receipt_session_endpoints" if default_basis == "receipt" else "recorded_session_endpoints"
        self.make_span(header_entry, (start, end), "invoke_agent", basis)

    def desired_parent(self, entry):
        record = entry.data
        if record["type"] == "session":
            return None
        if "parentCallId" in record:
            parent = self.unique_call(record["parentCallId"])
            return parent.data["id"] if parent else None
        if "inferenceId" in record:
            parent = self.by_id.get(record["inferenceId"])
            return parent.data["id"] if parent and parent.data["type"] == "inference" else None
        return self.session.header["id"]

    def connect_spans(self):
        parents = {key: self.desired_parent(self.by_id[key]) for key in self.spans}
        for key, parent in parents.items():
            seen, current = {key}, parent
            while current in parents and current not in seen:
                seen.add(current)
                current = parents[current]
            if current in seen:
                self.diagnostic(self.by_id[key], "cyclic_span_parent")
            elif parent in self.spans:
                self.spans[key]["parentSpanId"] = self.spans[parent]["spanId"]

    def record_target(self, entry):
        record = entry.data
        if record["id"] in self.spans:
            return self.spans[record["id"]]
        if record["type"] in {"approval", "tool_result", "file_change", "vcs"} and "callId" in record:
            call = self.unique_call(record["callId"])
            # A copied outcome cannot contribute events to an original operation.
            if call and not entry.copied and not call.copied:
                return self.spans.get(call.data["id"])
        if "inferenceId" in record:
            return self.spans.get(record["inferenceId"])
        return self.spans.get(self.session.header["id"])

    def build_logs(self, available):
        missing = []
        latest_totals = {}
        settings = {}
        for entry in self.session.entries:
            record = entry.data
            if record["type"] not in KNOWN:
                self.diagnostic(entry, "unknown_record_type")
                continue
            values = self.metadata(entry)
            missing = list(dict.fromkeys([*missing, *strings(record.get("missing"))]))
            if record["type"] == "session_info" and not entry.copied:
                for key in ("usage", "cost"):
                    if key in record:
                        latest_totals[key] = record[key]
                if "agentSettings" in record:
                    update_settings(settings, obj(record["agentSettings"]))
                    values["asr.agent_settings.effective"] = exact_json(settings)
                if isinstance(record.get("tools"), list):
                    values["asr.tools.count"] = len(record["tools"])
            if record["type"] == "inference" and record["id"] not in self.spans:
                self.inference_attributes(entry, values)
            unresolved = []
            for key in ("callId", "parentCallId"):
                if key in record and (key == "parentCallId" or record["type"] != "tool_call"):
                    call = self.unique_call(record[key])
                    if call is None:
                        unresolved.append(key)
                    elif record["type"] == "tool_result" and len(self.results.get(record[key], [])) != 1:
                        unresolved.append(key)
            if "inferenceId" in record:
                inference = self.by_id.get(record["inferenceId"])
                if inference is None or inference.data["type"] != "inference":
                    unresolved.append("inferenceId")
            parent = obj(record.get("parent"))
            for field, reference in (("parent.session", parent.get("session")),
                                     ("subagent.session", obj(record.get("subagent")).get("session")),
                                     ("message.from", record.get("from")),
                                     ("copiedFrom.session", obj(record.get("copiedFrom")).get("session"))):
                if isinstance(reference, str) and reference not in available:
                    unresolved.append(field)
            parent_export = available.get(parent.get("session"))
            if parent_export:
                if "record" in parent and parent["record"] not in parent_export.by_id:
                    unresolved.append("parent.record")
                if "callId" in parent and parent_export.unique_call(parent["callId"]) is None:
                    unresolved.append("parent.callId")
            copied = obj(record.get("copiedFrom"))
            source = available.get(copied.get("session"))
            if "record" in copied and (source is None or copied["record"] not in source.by_id):
                unresolved.append("copiedFrom.record")
            if record["type"] == "tool_call":
                result = self.paired_result(entry)
                values["asr.result.status"] = result.data.get("status", "unknown") if result and not result.copied else "unknown"
                if result is None:
                    unresolved.append("tool_result")
            if unresolved:
                values["asr.unresolved_references"] = unresolved
                self.diagnostic(entry, "unresolved_reference")
            if self.include_content:
                # This is an ASR record, never reconstructed model context.
                content = safe_content(record)
                if not self.include_identity:
                    content = {k: v for k, v in content.items() if k not in {"user", "person"}}
                values["asr.record.json"] = exact_json(content)
            target = self.record_target(entry)
            log = {"body": {"stringValue": "asr." + record["type"]},
                   "traceId": self.trace_id, "attributes": wire_attributes(values)}
            point = timestamp(record.get("ts"))
            if "ts" in record and point is None:
                self.diagnostic(entry, "invalid_timestamp")
            if point is not None:
                log["timeUnixNano"] = str(point)
            if target and not entry.copied:
                log["spanId"] = target["spanId"]
            self.logs.append(log)
            if (target and not entry.copied and point is not None
                    and record["type"] in {"approval", "gap", "session_info"}
                    and int(target["startTimeUnixNano"]) <= point <= int(target["endTimeUnixNano"])):
                target.setdefault("events", []).append({"name": "asr." + record["type"],
                                                        "timeUnixNano": str(point),
                                                        "attributes": wire_attributes(values)})
        # These reported totals are deliberately separate from standard per-call usage.
        summary = {"asr.missing": missing}
        for key, value in latest_totals.items():
            summary["asr.source_session_total." + key] = value
        merge_attributes(self.logs[0], summary)
        root = self.spans.get(self.session.header["id"])
        if root:
            merge_attributes(root, {"asr.missing": missing})


def update_settings(state, update):
    if "asks" not in update and any(k in update and update[k] != state.get(k)
                                    for k in ("mode", "approval", "sandbox")):
        state.pop("asks", None)
    for key, value in update.items():
        if value is None:
            state.pop(key, None)
        elif key == "modelSettings" and isinstance(value, dict):
            model = state.setdefault(key, {})
            for setting, supplied in value.items():
                if supplied is None:
                    model.pop(setting, None)
                else:
                    model[setting] = supplied
        else:
            state[key] = value


def add_link(span, target, relationship):
    span.setdefault("links", []).append({"traceId": target["traceId"], "spanId": target["spanId"],
                                         "attributes": attributes({"asr.relationship": relationship})})


def connect_sessions(exports):
    relationships = defaultdict(set)
    for reference, current in exports.items():
        parent = obj(current.session.header.get("parent"))
        if parent.get("kind") == "subagent" and isinstance(parent.get("session"), str):
            relationships[reference].add((parent["session"], parent.get("callId")))
        for entry in current.session.entries:
            if entry.copied or entry.data["type"] not in {"tool_call", "tool_result"}:
                continue
            child = obj(entry.data.get("subagent")).get("session")
            if isinstance(child, str):
                relationships[child].add((reference, entry.data.get("callId")))
    for child_ref, candidates in relationships.items():
        child = exports.get(child_ref)
        # A child-side link without callId can be completed by the parent's call.
        detailed = {pair for pair in candidates if pair[1] is not None}
        candidates = {pair for pair in candidates if pair[1] is not None or
                      not any(p[0] == pair[0] for p in detailed)}
        if child is None:
            continue
        if len(candidates) != 1:
            child.diagnostic(child.session.entries[0], "ambiguous_subagent_relationship")
            continue
        parent_ref, call_id = next(iter(candidates))
        parent = exports.get(parent_ref)
        call = parent.unique_call(call_id) if parent and call_id is not None else None
        parent_span = parent.spans.get(call.data["id"]) if call else (
            parent.spans.get(parent.session.header["id"]) if parent else None)
        child_span = child.spans.get(child.session.header["id"])
        if parent_span and child_span and child_ref != parent_ref:
            # Each session retains its own trace ID. Cross-trace relationships are links.
            add_link(child_span, parent_span, "subagent_of")
            add_link(parent_span, child_span, "delegates_to")
        else:
            child.diagnostic(child.session.entries[0], "subagent_span_unresolved")


def export_sessions(sessions: list[Session], contracts=None, *, include_content=False,
                    include_identity=False, user_name_kind=None) -> Export:
    mappings = validate_contracts(contracts) if contracts is not None else []
    exports = {}
    for session in sessions:
        if session.reference in exports:
            raise ValueError("duplicate_session")
        identity = {k: session.header["producer"][k] for k in ("name", "version", "method", "source")
                    if k in session.header["producer"]}
        contract = next((c for c in mappings if c["producer"] == identity), {})
        current = SessionExport(session, contract, include_content, include_identity, user_name_kind)
        current.build_spans()
        current.connect_spans()
        exports[session.reference] = current
    for current in exports.values():
        current.build_logs(exports)
    connect_sessions(exports)
    scope = {"name": "asr.otel", "version": VERSION,
             "attributes": attributes({"asr.semantic_conventions.gen_ai_revision": GENAI_REVISION,
                                        "asr.semantic_conventions.core_revision": CORE_REVISION,
                                        "asr.content.enabled": include_content,
                                        "asr.identity.enabled": include_identity})}
    resource = {"attributes": attributes({"service.name": "asr-otel"})}
    spans = [s for current in exports.values() for s in sorted(current.spans.values(),
             key=lambda s: next(int(a["value"]["intValue"]) for a in s["attributes"]
                                if a["key"] == "asr.record.index"))]
    logs = [log for current in exports.values() for log in current.logs]
    diagnostics = [{"source": index, **diagnostic} for index, current in enumerate(exports.values(), 1)
                   for diagnostic in current.diagnostics]
    return Export(
        {"resourceSpans": [{"resource": resource, "scopeSpans": [{"scope": scope, "spans": spans}]}] if spans else []},
        {"resourceLogs": [{"resource": resource, "scopeLogs": [{"scope": scope, "logRecords": logs}]}] if logs else []},
        {"sessions": len(exports), "spans": len(spans), "logs": len(logs), "diagnostics": diagnostics})
