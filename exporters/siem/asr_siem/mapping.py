"""Conservative mappings to the pinned OCSF 1.4.0 vocabulary."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import ipaddress
import re
from urllib.parse import quote, urlsplit, urlunsplit

from .reader import Session
from .safety import scrub

OCSF_VERSION = "1.4.0"
NETWORK_KEY = "org.agentsessionrecord.siem"
KNOWN = {"session", "session_info", "message", "inference", "tool_call", "tool_result", "approval", "file_change", "vcs", "gap"}


def component(text):
    return quote(text, safe="!$&'()*+,-./;=?@_~")


def reference(header):
    parts = [header["agent"]["name"]]
    if "namespace" in header:
        parts.append(component(header["namespace"]))
    parts.append(component(header["sessionId"]))
    return ":".join(parts)


def milliseconds(text):
    if not isinstance(text, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})", text):
        raise ValueError("invalid_timestamp")
    dt = datetime.fromisoformat(text.upper().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timezone_required")
    delta = dt.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return delta.days * 86400000 + delta.seconds * 1000 + delta.microseconds // 1000


def status_id(status):
    return {"completed": 1, "applied": 1, "failed": 2, "denied": 2}.get(status, 0)


def user(person):
    # A full name or email is not a username. Keep the ASR identity separately.
    if not isinstance(person, dict):
        return None
    result = {target: person[source] for source, target in [("id", "uid"), ("email", "email_addr"), ("name", "full_name")] if source in person}
    return result if "uid" in result else None


def file_object(path):
    return {"path": path, "name": path.rstrip("/").rsplit("/", 1)[-1], "type_id": 0}


def public_settings(settings):
    result = {key: settings[key] for key in ("mode", "asks", "modelSettings") if key in settings}
    if "externalSandbox" in settings:
        result["externalSandbox"] = {key: value for key, value in settings["externalSandbox"].items() if key in ("kind", "source")}
    return result


def update_settings(state, update):
    if any(key in update for key in ("mode", "approval", "sandbox")) and "asks" not in update:
        state.pop("asks", None)
    for key, value in update.items():
        if value is None:
            state.pop(key, None)
        elif key == "modelSettings":
            nested = state.setdefault(key, {})
            for name, setting in value.items():
                if setting is None:
                    nested.pop(name, None)
                else:
                    nested[name] = setting
        else:
            state[key] = value


@dataclass
class Export:
    events: list[dict]
    report: dict


def convert(session: Session, *, include_content=False, observed_at=None, device_uid=None) -> Export:
    records = session.records
    header = records[0]
    ref = reference(header)
    diagnostics = list(session.diagnostics)
    calls, results = defaultdict(list), defaultdict(list)
    by_id = {r["id"]: r for r in records}
    for record in records:
        if record["type"] in ("tool_call", "tool_result") and isinstance(record.get("callId"), str):
            (calls if record["type"] == "tool_call" else results)[record["callId"]].append(record)
    boundary = header.get("parent", {}).get("copiedThrough")
    if boundary is not None and (boundary not in by_id or boundary == header["id"]):
        raise ValueError("invalid_copied_boundary")
    prefix_end = next((i for i, r in enumerate(records) if r["id"] == boundary), -1)
    missing, settings, events, pending = set(), {}, [], []
    if observed_at is not None:
        milliseconds(observed_at)
    related = set()

    def emit(record, index, code, class_uid=0, activity=99, **fields):
        citation = ref + "#" + component(record["id"])
        uid = hashlib.sha256((citation + ":" + code).encode()).hexdigest()
        copied = "copiedFrom" in record or 0 < index <= prefix_end
        info = {"session": ref, "record": citation, "record_type": record["type"],
                "position": index, "credited": not copied, "missing": sorted(missing),
                "content_included": include_content}
        for key in ("callId", "turnId", "inferenceId", "truncated"):
            if key in record:
                info[key] = record[key]
        if copied:
            info["copy_source"] = record["copiedFrom"] if "copiedFrom" in record else {"session": header["parent"]["session"]}
            info["mapped_class_uid"] = class_uid
            class_uid, activity, fields, code = 0, 99, {}, "asr.copy"
        data = {"category_uid": class_uid // 1000, "class_uid": class_uid,
                "activity_id": activity, "type_uid": class_uid * 100 + activity,
                "severity_id": 0, "status_id": 0,
                "metadata": {"version": OCSF_VERSION, "uid": uid, "event_code": code,
                             "product": {"name": "ASR SIEM exporter", "vendor_name": "Agent Session Record", "version": "0.1.0"}},
                "unmapped": {"asr": info}}
        info["time_source"] = "record" if "ts" in record else "unknown"
        if "ts" in record:
            try:
                data["time"] = milliseconds(record["ts"])
                info["ts"] = record["ts"]
            except (ValueError, TypeError, AttributeError):
                diagnostics.append({"code": "invalid_time", "record": citation})
        elif observed_at is not None:
            data["time"] = milliseconds(observed_at)
            data["metadata"]["logged_time"] = data["time"]
            info["time_source"] = "explicit_observation"
        unknown_file_actor = class_uid == 1001 and (
            record.get("actor") in ("human", "external", "hook")
            or ("actor" not in record and len(calls.get(record.get("callId"), [])) != 1)
            or record.get("actor") not in (None, "harness")
        )
        if class_uid in (1001, 1007) and (not device_uid or unknown_file_actor):
            info["mapped_class_uid"] = class_uid
            info["system_activity"] = fields
            info["ocsf_missing"] = ([] if device_uid else ["device.identity"]) + (["actor.identity"] if unknown_file_actor else [])
            data.update(category_uid=0, class_uid=0, activity_id=99, type_uid=99)
            for field in info["ocsf_missing"]:
                diagnostics.append({"code": field.replace(".", "_") + "_missing", "record": citation})
            class_uid, fields = 0, {}
        data.update(fields)
        if class_uid in (1001, 1007):
            data["device"] = {"uid": device_uid, "type_id": 0}
            data["actor"] = {"app_name": header["agent"]["name"]}
        if class_uid == 0 and "actor" in data:
            data["metadata"]["profiles"] = ["host"]
        if "time" in data:
            events.append(scrub(data))
        else:
            diagnostics.append({"code": "time_missing", "record": citation})
            pending.append(scrub(data))
        return data

    for index, record in enumerate(records):
        kind = record["type"]
        citation = ref + "#" + component(record["id"])
        copied = "copiedFrom" in record or 0 < index <= prefix_end
        for source in (record.get("copiedFrom", {}), record.get("parent", {}), record.get("subagent", {})):
            if isinstance(source, dict) and "session" in source:
                related.add(source["session"])
        if isinstance(record.get("from"), str):
            related.add(record["from"])
        if record.get("inferenceId") is not None and by_id.get(record["inferenceId"], {}).get("type") != "inference":
            diagnostics.append({"code": "unresolved_inference", "record": citation})
        if kind not in KNOWN:
            diagnostics.append({"code": "unknown_type", "record": citation})
            continue
        if kind in ("session", "session_info"):
            missing.update(record.get("missing", []))
            if not copied and "agentSettings" in record:
                update_settings(settings, record["agentSettings"])
        extra = {}
        if kind == "file_change":
            if not isinstance(record.get("path"), str) or "op" not in record or "status" not in record:
                diagnostics.append({"code": "invalid_file_change", "record": citation})
                continue
            activity = {"add": 1, "modify": 3, "delete": 4, "move": 5, "copy": 99}.get(record["op"], 0)
            extra = {"file": file_object(record["path"]), "status_id": status_id(record["status"])}
            if "oldPath" in record:
                extra["file"] = file_object(record["oldPath"])
                extra["file_result"] = file_object(record["path"])
            event = emit(record, index, "asr.file_change", 1001, activity, **extra)
        elif kind == "approval":
            if not isinstance(record.get("decision"), str):
                diagnostics.append({"code": "invalid_approval", "record": citation})
                continue
            actor = {"app_name": header["agent"]["name"], "authorizations": [{"decision": record["decision"]}]}
            answerer = user(record.get("person"))
            if answerer:
                actor["user"] = answerer
            event = emit(record, index, "asr.authorization", actor=actor)
        elif kind == "tool_call" and record.get("kind") == "execute":
            # A request is not evidence of an operating-system process or its success.
            process = {"uid": "asr-command:" + hashlib.sha256(citation.encode()).hexdigest()}
            event = emit(record, index, "asr.command.request", 1007, 1, process=process)
        elif kind == "tool_result" and isinstance(record.get("exec"), dict):
            execution = record["exec"]
            linked = calls.get(record.get("callId"), [])
            origin = ref + "#" + component(linked[0]["id"]) if len(linked) == 1 and len(results.get(record.get("callId"), [])) == 1 else citation
            process = {"uid": "asr-command:" + hashlib.sha256(origin.encode()).hexdigest()}
            extra = {"process": process, "status_id": status_id(record.get("status"))}
            if "exitCode" in execution:
                extra["exit_code"] = execution["exitCode"]
            event = emit(record, index, "asr.command.result", 1007, 99, **extra)
        else:
            event = emit(record, index, "asr." + kind)
        info = event["unmapped"]["asr"]
        # emit has already scrubbed the first snapshot. Update only through scrub below.
        for key in ("status", "op", "actor", "requestedBy", "kind", "name", "decision", "by", "scope", "person"):
            if key in record:
                info[key] = scrub(record[key])
        if kind == "approval" and include_content and "subject" in record:
            info["subject"] = scrub(record["subject"])
        if kind in ("session", "session_info"):
            if settings:
                info["agent_settings"] = scrub(settings if include_content else public_settings(settings))
            if "parent" in record:
                info["parent"] = scrub(record["parent"])
        if kind == "gap":
            for key in ("reason", "count"):
                if key in record:
                    info[key] = scrub(record[key])
        call_id = record.get("callId")
        if kind in ("tool_call", "tool_result", "approval", "file_change", "vcs") and call_id is not None:
            linked = calls.get(call_id, [])
            info["pairing"] = "unique" if len(linked) == 1 else "ambiguous" if linked else "missing"
            if len(linked) != 1:
                diagnostics.append({"code": "unpaired_call_reference", "record": citation})
            if len(linked) == 1 and kind != "tool_call":
                info["call_record"] = ref + "#" + component(linked[0]["id"])
        if kind == "tool_call":
            outcomes = results.get(call_id, [])
            info["outcome"] = "unknown"
            if len(calls.get(call_id, [])) == 1 and len(outcomes) == 1:
                info["result_record"] = ref + "#" + component(outcomes[0]["id"])
            else:
                diagnostics.append({"code": "unknown_call_outcome", "record": citation})
        if kind == "tool_result" and call_id is not None and len(results[call_id]) != 1:
            info["pairing"] = "ambiguous_results"
            diagnostics.append({"code": "duplicate_results", "record": citation})
        if include_content:
            selected = {key: record[key] for key in ("input", "inputText", "content", "exec", "patch", "edits", "before", "after", "detail") if key in record}
            linked = calls.get(call_id, [])
            outcomes = results.get(call_id, [])
            effective = record if kind == "tool_result" and len(linked) == 1 and len(outcomes) == 1 else outcomes[0] if kind == "tool_call" and len(linked) == 1 and len(outcomes) == 1 else None
            if effective is not None:
                for key in ("input", "inputText"):
                    if key in effective:
                        selected["effective_input"] = effective[key]
            info["content"] = scrub(selected)
        # Replace the snapshot after attaching the selected ASR metadata.
        destination = events if "time" in event else pending
        destination[-1] = scrub(event)
        if kind == "tool_result" and not copied:
            for network in network_events(record, diagnostics, citation, include_content):
                emit(record, index, **network)
    for related_ref in sorted(related - {ref}):
        diagnostics.append({"code": "unresolved_session", "session": related_ref})
    report = {"session": ref, "records_read": len(records), "events_emitted": len(events),
              "content_included": include_content, "missing": sorted(missing),
              "unresolved_sessions": sorted(related - {ref}), "diagnostics": diagnostics,
              "untimed_events": pending}
    return Export(events, scrub(report))


def network_events(record, diagnostics, citation, include_content):
    metadata = record.get("_meta", {}).get(NETWORK_KEY, {})
    network = metadata.get("network") if isinstance(metadata, dict) else None
    if not isinstance(network, dict) or network.get("observed") is not True:
        return []
    endpoints = {}
    for source, target in (("src", "src_endpoint"), ("dst", "dst_endpoint")):
        value = network.get(source)
        if isinstance(value, dict) and any(isinstance(value.get(k), str) and value[k] for k in ("ip", "hostname")):
            endpoint = {}
            if isinstance(value.get("hostname"), str) and value["hostname"]:
                endpoint["hostname"] = value["hostname"]
            if isinstance(value.get("ip"), str):
                try:
                    ipaddress.ip_address(value["ip"])
                    endpoint["ip"] = value["ip"]
                except ValueError:
                    diagnostics.append({"code": "invalid_network_ip", "record": citation})
            if endpoint:
                if type(value.get("port")) is int and 0 <= value["port"] <= 65535:
                    endpoint["port"] = value["port"]
                endpoints[target] = endpoint
    if not endpoints:
        diagnostics.append({"code": "network_endpoint_missing", "record": citation})
        return []
    http = network.get("http")
    valid_code = isinstance(http, dict) and type(http.get("status")) is int and 100 <= http["status"] <= 599
    if isinstance(http, dict) and (isinstance(http.get("method"), str) or valid_code):
        fields = dict(endpoints)
        method = http.get("method")
        if isinstance(method, str):
            fields["http_request"] = {"http_method": method}
            if isinstance(http.get("url"), str):
                try:
                    url = urlsplit(http["url"])
                    authority = (url.hostname or "") + (":" + str(url.port) if url.port else "")
                    clean = urlunsplit((url.scheme, authority, url.path, url.query if include_content else "", ""))
                    fields["http_request"]["url"] = {"url_string": clean}
                except ValueError:
                    diagnostics.append({"code": "invalid_http_url", "record": citation})
        if valid_code:
            fields["http_response"] = {"code": http["status"]}
        activity = {"CONNECT": 1, "DELETE": 2, "GET": 3, "HEAD": 4, "OPTIONS": 5, "POST": 6, "PUT": 7, "TRACE": 8}.get(method, 99 if method else 0)
        return [{"code": "asr.http.observed", "class_uid": 4002, "activity": activity, **fields}]
    activity = {"open": 1, "close": 2, "reset": 3, "fail": 4, "refuse": 5, "traffic": 6, "listen": 7}.get(network.get("activity"), 0)
    return [{"code": "asr.network.observed", "class_uid": 4001, "activity": activity, **endpoints}]
