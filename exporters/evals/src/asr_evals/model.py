"""Neutral evidence views and explicitly sourced observation intervals."""

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import re

from .reader import CORE, stable_id


def pick(value, keys):
    return {key: deepcopy(value[key]) for key in keys if key in value}


def timestamp_ns(value):
    if not isinstance(value, str):
        return None
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00").replace("z", "+00:00"))
        if instant.tzinfo is None:
            return None
        delta = instant.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
        # Preserve nanosecond RFC 3339 fractions beyond datetime's precision.
        fraction = value.split("T", 1)[-1].split(".", 1)
        extra = 0
        if len(fraction) == 2:
            digits = re.match(r"\d*", fraction[1]).group()
            extra = int((digits + "000000000")[:9]) % 1000
        return (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000 + extra
    except (ValueError, OverflowError):
        return None


def iso_ns(value):
    seconds, nanos = divmod(value, 1_000_000_000)
    return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + f".{nanos:09d}Z"


def interval(session, record, inference_ts="unknown", tool_times=False):
    start = end = None
    basis = "recorded"
    if record["type"] == "session":
        start, end = timestamp_ns(record.get("startedAt")), timestamp_ns(session.latest.get("endedAt"))
        if start is not None and end is not None:
            observed = [timestamp_ns(r.get("ts")) for r in session.records if session.original(r)]
            if any(t is not None and not start <= t <= end for t in observed):
                return None
    elif record["type"] == "inference" and inference_ts != "unknown":
        stamp = timestamp_ns(record.get("ts"))
        duration = record.get("durationMs")
        if stamp is not None and isinstance(duration, (int, Decimal)) and not isinstance(duration, bool) and duration >= 0:
            nanos = int(Decimal(duration) * 1_000_000)
            start, end = (stamp, stamp + nanos) if inference_ts == "start" else (stamp - nanos, stamp)
            basis = "operator_declared_inference_ts_" + inference_ts
    elif record["type"] == "tool_call":
        result = session.result(record)
        receipt = session.header.get("producer", {}).get("method") == "recorder"
        if result is not None and session.original(result) and (tool_times or receipt):
            start, end = timestamp_ns(record.get("ts")), timestamp_ns(result.get("ts"))
            basis = "receipt_interval" if receipt else "operator_declared_tool_endpoints"
    if start is None or end is None or start < 0 or end < start:
        return None
    return {"start": start, "end": end, "basis": basis}


def content(parts):
    if not isinstance(parts, list):
        return []
    result = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        kind = part.get("type")
        if kind == "text":
            result.append(pick(part, ("type", "text", "author", "origin")))
        elif kind == "reasoning":
            keys = ("type", "visibility") if part.get("visibility") in ("encrypted", "omitted") else ("type", "text", "summary", "visibility")
            result.append(pick(part, keys))
        elif kind in ("image", "audio", "resource_link", "resource"):
            # Keep links as data. Never resolve media or resource references.
            result.append(deepcopy(part))
    return result


def record_view(session, record, include_content=False):
    fields = {
        "session_info": ("title", "endedAt", "usage", "cost", "missing"),
        "message": ("role", "author", "origin", "phase", "status", "from"),
        "tool_call": ("callId", "name", "kind", "requestedBy", "parentCallId", "locations", "subagent"),
        "tool_result": ("callId", "status", "durationMs", "subagent"),
        "approval": ("callId", "decision", "by", "scope"),
        "file_change": ("path", "op", "oldPath", "status", "callId", "actor", "baseCommit"),
        "vcs": ("action", "status", "evidence", "callId", "actor", "repo", "commit", "commitPrefix", "parents", "parentCount", "headBefore", "headAfter", "rewrites", "branch", "pr"),
        "inference": ("model", "settings", "usage", "cost", "stopReason", "durationMs"),
        "gap": ("reason", "count"),
    }
    view = pick(record, ("type", "id", "ts", "turnId", "inferenceId", "copiedFrom", "truncated") + fields.get(record["type"], ()))
    view["reference"] = session.cite(record)
    view["line"] = session.lines.get(record["id"])
    view["original"] = session.original(record)
    if record["type"] == "session_info":
        settings = record.get("agentSettings", {})
        view["agentSettings"] = deepcopy(settings) if include_content else pick(settings, ("mode", "asks", "modelSettings"))
        view["effectiveSettings"] = deepcopy(session.settings[record["id"]]) if include_content else pick(session.settings[record["id"]], ("mode", "asks", "modelSettings"))
        if "tools" in record:
            view["tools"] = deepcopy(record["tools"]) if include_content else [pick(t, ("name", "source")) for t in record["tools"]]
    if record["type"] == "tool_call":
        result = session.result(record)
        view["outcome"] = result["status"] if result is not None else "unknown"
        if result is not None:
            view["result"] = session.cite(result)
    if record["type"] == "tool_result":
        call = session.call(record.get("callId"))
        view["pairing"] = "paired" if call is not None and session.result(call) is record else "unpaired"
        if view["pairing"] == "paired":
            view["call"] = session.cite(call)
    if record["type"] == "approval" and "callId" in record:
        call = session.call(record["callId"])
        view["pairing"] = "paired" if call is not None else "unpaired"
        if call is not None:
            view["call"] = session.cite(call)
    if include_content:
        view.update(pick(record, ("input", "inputText", "patch", "edits", "before", "after", "subject", "native", "detail", "error")))
        if "content" in record:
            view["content"] = content(record["content"])
    if isinstance(record.get("exec"), dict):
        view["exec"] = deepcopy(record["exec"]) if include_content else pick(record["exec"], ("exitCode", "signal"))
    return view


def observations(session, include_content=False, inference_ts="unknown", tool_times=False):
    result = []
    selected = [session.header] + [r for r in session.records if session.original(r) and r["type"] in ("inference", "tool_call")]
    for record in selected:
        kind = record["type"]
        item = {"id": stable_id(session.cite(record), 8), "trace_id": stable_id(session.ref),
                "kind": kind, "reference": session.cite(record), "record": record,
                "metadata": {"asr.reference": session.cite(record), "asr.original": True,
                             "asr.line": session.lines.get(record["id"], 1)}}
        item["name"] = "asr.session" if kind == "session" else (record.get("name", "asr.tool") if kind == "tool_call" else "asr.inference")
        item["interval"] = interval(session, record, inference_ts, tool_times)
        if "truncated" in record:
            item["metadata"]["asr.truncated"] = record["truncated"]
        if item["interval"]:
            item["metadata"]["asr.timing_basis"] = item["interval"]["basis"]
        if kind == "session":
            item["metadata"].update({"asr.session": session.ref, "asr.missing": sorted(session.missing), "asr.agent": session.header["agent"]})
        elif kind == "inference":
            item["metadata"].update({"asr." + k: v for k, v in pick(record, ("model", "settings", "usage", "cost", "stopReason", "durationMs")).items()})
            if include_content:
                outputs = [dict(reference=session.cite(r), content=content(r["content"]), **pick(r, ("truncated", "status"))) for r in session.records
                           if r["type"] == "message" and r.get("inferenceId") == record["id"] and session.original(r)]
                if outputs:
                    item["output"] = outputs
        elif kind == "tool_call":
            paired = session.result(record)
            item["metadata"]["asr.outcome"] = paired["status"] if paired is not None else "unknown"
            item["metadata"]["asr.call_id"] = record["callId"]
            if paired is not None and "truncated" in paired:
                item["metadata"]["asr.result_truncated"] = paired["truncated"]
            if include_content:
                supplied = session.effective_input(record)
                if supplied:
                    item["input"] = next(iter(supplied.values()))
                if paired is not None and "content" in paired:
                    item["output"] = content(paired["content"])
            if paired is not None and paired.get("status") in ("failed", "denied"):
                item["error"] = True
        if "error" in record:
            item["error"] = True
        result.append(item)
    # Resolve parent links by identity, never proximity. Reject cycles.
    by_record = {o["record"]["id"]: o for o in result}
    root = result[0]
    for item in result[1:]:
        record = item["record"]
        parent = root
        if record["type"] == "tool_call":
            call = session.call(record.get("parentCallId"))
            if call and call["id"] in by_record:
                parent = by_record[call["id"]]
            elif record.get("inferenceId") in by_record and by_record[record["inferenceId"]]["kind"] == "inference":
                parent = by_record[record["inferenceId"]]
        item["parent_id"] = parent["id"]
    by_id = {o["id"]: o for o in result}
    for item in result:
        seen = {item["id"]}
        parent_id = item.get("parent_id")
        while parent_id:
            if parent_id in seen:
                item.pop("parent_id", None)
                item["metadata"]["asr.unresolved_parent"] = "cycle"
                break
            seen.add(parent_id)
            parent_id = by_id[parent_id].get("parent_id")
    return result


def audit(sessions, annotations=(), include_content=False):
    by_ref = {s.ref: s for s in sessions}
    unresolved, relations = [], {}
    def link(source, target, code):
        ref, _, fragment = target.partition("#")
        found = by_ref.get(ref)
        if found is None or (fragment and target not in {found.cite(r) for r in [found.header] + found.records}):
            unresolved.append({"source": source, "target": target, "code": code})
    for session in sessions:
        parent = session.header.get("parent")
        if parent:
            link(session.ref, parent["session"], "related_session")
            if "record" in parent:
                from .reader import component
                link(session.ref, parent["session"] + "#" + component(parent["record"]), "parent_record")
            if "callId" in parent:
                source_session = by_ref.get(parent["session"])
                if source_session is None or source_session.call(parent["callId"]) is None:
                    unresolved.append({"source": session.ref, "target": parent["callId"], "code": "parent_call"})
            if parent.get("kind") == "subagent":
                relations[(parent["session"], parent.get("callId"), session.ref)] = {"parent": parent["session"], "call_id": parent.get("callId"), "child": session.ref}
        for record in session.records:
            source = session.cite(record)
            if record["type"] not in CORE:
                continue
            for key in ("inferenceId",):
                if key in record and session.by_id.get(record[key], {}).get("type") != "inference":
                    unresolved.append({"source": source, "target": record[key], "code": "inference"})
            if "callId" in record and record["type"] != "tool_call" and session.call(record["callId"]) is None:
                unresolved.append({"source": source, "target": record["callId"], "code": "call"})
            if record["type"] == "tool_result" and "callId" not in record:
                unresolved.append({"source": source, "code": "unpaired_result"})
            elif record["type"] == "tool_result":
                call = session.call(record["callId"])
                if call is not None and session.result(call) is not record:
                    unresolved.append({"source": source, "target": record["callId"], "code": "ambiguous_result"})
            if record["type"] == "tool_call" and "parentCallId" in record and session.call(record["parentCallId"]) is None:
                unresolved.append({"source": source, "target": record["parentCallId"], "code": "parent_call"})
            if record["type"] == "tool_call" and session.result(record) is None:
                unresolved.append({"source": source, "target": record["callId"], "code": "result_unknown"})
            if "from" in record:
                link(source, record["from"], "message_source")
            copied = record.get("copiedFrom", {})
            if copied:
                if "session" not in copied:
                    unresolved.append({"source": source, "target": copied.get("record"), "code": "copy_source_session_unknown"})
                else:
                    target = copied["session"]
                    if "record" in copied:
                        from .reader import component
                        target += "#" + component(copied["record"])
                    link(source, target, "copy_source")
            subagent = record.get("subagent", {})
            child = subagent.get("session")
            if child:
                link(source, child, "related_session")
                key = (session.ref, record.get("callId"), child)
                relations[key] = {"parent": session.ref, "call_id": record.get("callId"), "child": child}
    # A child-only link without a call ID joins a unique parent-side link.
    for key in list(relations):
        if key[1] is None and sum(k[0] == key[0] and k[2] == key[2] for k in relations) > 1:
            del relations[key]
    for item in annotations:
        link("annotation:" + item["id"], item["session"], "annotation_target")
    return {"format": "asr-observability-audit-v1", "content_included": include_content,
            "sessions": [{"session": s.ref, "source_sha256": s.digest,
                          "missing": sorted(s.missing), "accounting": s.accounting(),
                          "diagnostics": s.diagnostics,
                          "records": [record_view(s, r, include_content) for r in s.records if r["type"] in CORE]}
                         for s in sessions], "relationships": list(relations.values()), "unresolved": unresolved}
