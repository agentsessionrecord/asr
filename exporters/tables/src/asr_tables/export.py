"""Convert source facts to flat rows without manufacturing missing evidence."""

from collections import defaultdict
from copy import deepcopy
from decimal import Decimal, localcontext
from pathlib import Path
import shutil
import tempfile

import pyarrow as pa
import pyarrow.parquet as pq

from .reader import ExportError, dumps, read_stream, record_ref, session_ref
from .schema import SCHEMAS


def json_field(record, key):
    return dumps(record[key]) if key in record else None


def money(cost):
    if not cost:
        return {}
    exact = Decimal(cost["amount"])
    with localcontext() as context:
        context.prec = max(80, len(exact.as_tuple().digits) + 20)
        normalized = exact.normalize()
        fits = (exact.is_finite() and abs(exact) < Decimal(10) ** 20
                and (exact.is_zero() or normalized.as_tuple().exponent >= -18))
    return dict(cost_amount=exact if fits else None, cost_amount_text=str(exact),
                cost_currency=cost.get("currency"), cost_source=cost.get("source"))


def usage(record):
    value = record.get("usage", {})
    return {column: value.get(field) for column, field in [
        ("input_tokens", "inputTokens"), ("cache_read_tokens", "cacheReadTokens"),
        ("cache_write_tokens", "cacheWriteTokens"), ("output_tokens", "outputTokens"),
        ("reasoning_tokens", "reasoningTokens"),
    ]}


def update_settings(state, patch):
    state = deepcopy(state)
    changed_policy = any(key in patch and patch[key] != state.get(key)
                         for key in ("mode", "approval", "sandbox"))
    if changed_policy and "asks" not in patch:
        state.pop("asks", None)
    for key, value in patch.items():
        if value is None:
            state.pop(key, None)
        elif key == "modelSettings":
            if not value:
                continue
            model = state.setdefault(key, {})
            for field, setting in value.items():
                if setting is None:
                    model.pop(field, None)
                else:
                    model[field] = deepcopy(setting)
        else:
            state[key] = deepcopy(value)
    return state


def project(stream, tables):
    header, records = stream.header, stream.records
    ref = session_ref(header)
    calls, results = defaultdict(list), defaultdict(list)
    for position, record, _ in records:
        if record["type"] == "tool_call" and isinstance(record.get("callId"), str):
            calls[record["callId"]].append((position, record))
        elif record["type"] == "tool_result" and isinstance(record.get("callId"), str):
            results[record["callId"]].append((position, record))
    parent = header.get("parent", {})
    boundary = parent.get("copiedThrough")
    boundary_pos = next((pos for pos, rec, _ in records[1:] if rec["id"] == boundary), None)
    if boundary is not None and boundary_pos is None:
        tables["diagnostics"].append(dict(source_index=stream.source_index, line=1,
                                          code="unresolved-copy-boundary", severity="error"))

    def original(pos, rec):
        return ("copiedFrom" not in rec and (boundary is None or pos == 1
                or (boundary_pos is not None and pos > boundary_pos)))

    def paired_call(rec):
        matching = calls.get(rec.get("callId"), [])
        return matching[0][1]["id"] if len(matching) == 1 else None

    def link(record, position, kind, target, target_record=None):
        if target or target_record:
            tables["links"].append(dict(session_ref=ref, record_id=record["id"],
                position=position, kind=kind, target_session=target,
                target_record=target_record, resolved=False))

    missing = list(dict.fromkeys(header.get("missing", []))) if "missing" in header else None
    repos = deepcopy(header.get("repos"))
    state, tools, latest_usage, latest_cost = {}, None, None, None
    settings_seen = False
    title, ended = header.get("title"), header.get("endedAt")
    for pos, rec, raw in records:
        typ = rec["type"]
        common = dict(session_ref=ref, record_id=rec["id"], record_ref=record_ref(ref, rec["id"]),
            position=pos, ts=rec.get("ts"), turn_id=rec.get("turnId"),
            inference_id=rec.get("inferenceId"), original=original(pos, rec),
            copied_from_json=json_field(rec, "copiedFrom"), truncated=rec.get("truncated"))
        tables["records"].append(dict(common, record_type=typ, raw_json=raw))
        copy = rec.get("copiedFrom", {})
        link(rec, pos, "copied_from", copy.get("session"), copy.get("record"))
        if "inferenceId" in rec:
            link(rec, pos, "inference", ref, rec["inferenceId"])
        if typ == "session":
            link(rec, pos, "parent_" + parent.get("kind", "unknown"), parent.get("session"),
                 parent.get("record"))
        if typ in ("tool_call", "tool_result"):
            link(rec, pos, "subagent", rec.get("subagent", {}).get("session"))
        if typ == "message":
            tables["messages"].append(dict(common, **{
                field: rec.get(field) for field in ("role", "author", "origin", "phase", "status")},
                from_session=rec.get("from"), person_json=json_field(rec, "person"),
                content_json=json_field(rec, "content")))
            link(rec, pos, "message_from", rec.get("from"))
        elif typ == "tool_call":
            call_id = rec.get("callId")
            matches = results.get(call_id, [])
            unique = len(calls.get(call_id, [])) == 1 and len(matches) == 1
            result_pos, result = matches[0] if unique else (None, {})
            effective = result if "input" in result or "inputText" in result else rec
            tables["tool_calls"].append(dict(common, call_id=call_id,
                name=rec.get("name"), kind=rec.get("kind"), requested_by=rec.get("requestedBy"),
                parent_call_id=rec.get("parentCallId"), input_json=json_field(rec, "input"),
                input_text=rec.get("inputText"), locations_json=json_field(rec, "locations"),
                subagent_json=json_field(rec, "subagent"), pairing="paired" if unique else
                ("ambiguous" if len(calls.get(call_id, [])) > 1 or len(matches) > 1 else "missing"),
                result_record_id=result.get("id"), result_position=result_pos,
                result_original=original(result_pos, result) if unique else None,
                outcome=result.get("status", "unknown"),
                effective_input_json=json_field(effective, "input"),
                effective_input_text=effective.get("inputText"),
                result_content_json=json_field(result, "content"),
                result_error_json=json_field(result, "error"), exec_json=json_field(result, "exec"),
                duration_ms_text=str(result["durationMs"]) if "durationMs" in result else None))
        elif typ == "tool_result":
            call_id = rec.get("callId")
            unique = paired_call(rec) is not None and len(results.get(call_id, [])) == 1
            tables["tool_results"].append(dict(common, call_id=call_id,
                paired_call_record_id=paired_call(rec) if unique else None,
                pairing="paired" if unique else "unpaired", status=rec.get("status"),
                **{key + "_json": json_field(rec, key) for key in
                   ("content", "input", "error", "exec", "subagent")},
                input_text=rec.get("inputText"),
                duration_ms_text=str(rec["durationMs"]) if "durationMs" in rec else None))
        elif typ == "approval":
            tables["approvals"].append(dict(common, call_id=rec.get("callId"),
                paired_call_record_id=paired_call(rec), decision=rec.get("decision"),
                decider=rec.get("by"), scope=rec.get("scope"), subject=rec.get("subject"),
                person_json=json_field(rec, "person"), native_json=json_field(rec, "native")))
        elif typ == "file_change":
            tables["file_changes"].append(dict(common, call_id=rec.get("callId"),
                paired_call_record_id=paired_call(rec), path=rec.get("path"),
                old_path=rec.get("oldPath"), op=rec.get("op"), status=rec.get("status"),
                actor=rec.get("actor"), base_commit=rec.get("baseCommit"), patch=rec.get("patch"),
                **{key + "_json": json_field(rec, key) for key in ("before", "after", "edits")}))
        elif typ == "vcs":
            row = dict(common, call_id=rec.get("callId"), paired_call_record_id=paired_call(rec))
            for output, source in {
                "action": "action", "status": "status", "evidence": "evidence", "actor": "actor",
                "repo": "repo", "commit_id": "commit", "commit_prefix": "commitPrefix",
                "subject": "subject", "parent_count": "parentCount", "head_before": "headBefore",
                "head_after": "headAfter", "branch": "branch", "remote": "remote",
            }.items():
                row[output] = rec.get(source)
            row.update({key + "_json": json_field(rec, key) for key in ("parents", "rewrites", "pr")})
            tables["vcs"].append(row)
        elif typ == "inference":
            model = rec.get("model", {})
            tables["inferences"].append(dict(common, model_provider=model.get("provider"),
                model_id=model.get("id"), model_requested=model.get("requested"),
                settings_json=json_field(rec, "settings"), **usage(rec), **money(rec.get("cost")),
                stop_reason=rec.get("stopReason"), error_json=json_field(rec, "error"),
                duration_ms_text=str(rec["durationMs"]) if "durationMs" in rec else None))
        elif typ == "session_info":
            tables["session_updates"].append(dict(common, title=rec.get("title"),
                ended_at=rec.get("endedAt"), **{key + "_json": json_field(rec, key)
                for key in ("repos", "missing", "tools", "usage", "cost")},
                includes_subagents=rec.get("usage", {}).get("includesSubagents"),
                **usage(rec), **money(rec.get("cost"))))
            if "title" in rec:
                title = rec["title"]
            if "endedAt" in rec:
                ended = rec["endedAt"]
            if "repos" in rec:
                repos = (repos or []) + deepcopy(rec["repos"])
            if "missing" in rec:
                missing = list(dict.fromkeys((missing or []) + rec["missing"]))
            if "usage" in rec and common["original"]:
                latest_usage = rec["usage"]
            if "cost" in rec and common["original"]:
                latest_cost = rec["cost"]
            if "tools" in rec:
                tools = rec["tools"]
            if "agentSettings" in rec:
                settings_seen = True
                state = update_settings(state, rec["agentSettings"])
                tables["settings_changes"].append(dict(common,
                    update_json=dumps(rec["agentSettings"]), effective_json=dumps(state)))
        elif typ == "gap":
            tables["gaps"].append(dict(common, reason=rec.get("reason"),
                                      count=rec.get("count"), detail=rec.get("detail")))
    user, agent, producer = header.get("user", {}), header["agent"], header.get("producer", {})
    tables["sessions"].append(dict(session_ref=ref, session_id=header["sessionId"],
        namespace=header.get("namespace"), agent_name=agent["name"], agent_version=agent.get("version"),
        **{"user_" + key: user.get(key) for key in ("id", "email", "name", "source")},
        **{"producer_" + key: producer.get(key) for key in ("name", "version", "method", "source")},
        started_at=header.get("startedAt"), ended_at=ended, title=title, cwd=header.get("cwd"),
        parent_session=parent.get("session"), parent_kind=parent.get("kind"),
        repos_json=dumps(repos) if repos is not None else None,
        missing_json=dumps(missing) if missing is not None else None,
        tools_json=dumps(tools) if tools is not None else None,
        agent_settings_json=dumps(state) if settings_seen else None,
        latest_usage_json=dumps(latest_usage) if latest_usage is not None else None,
        latest_cost_json=dumps(latest_cost) if latest_cost is not None else None,
        includes_subagents=latest_usage.get("includesSubagents") if latest_usage is not None else None,
        source_sha256=stream.digest, source_index=stream.source_index, record_count=len(records)))


def export(paths, output):
    """Write a new dataset. Conflicting revisions and existing destinations are rejected."""
    output = Path(output)
    if output.exists():
        raise ExportError("output-exists")
    tables = {name: [] for name in SCHEMAS}
    seen = {}
    for index, path in enumerate(paths, 1):
        stream = read_stream(Path(path), index)
        ref = session_ref(stream.header)
        if ref in seen:
            if seen[ref] != stream.digest:
                raise ExportError("conflicting-session-revisions")
            tables["diagnostics"].append(dict(source_index=index, line=1,
                                             code="duplicate-session-skipped", severity="info"))
            continue
        seen[ref] = stream.digest
        tables["diagnostics"].extend(stream.diagnostics)
        try:
            project(stream, tables)
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ExportError("invalid-record-shape") from None
    records = {(row["session_ref"], row["record_id"]): row["record_type"] for row in tables["records"]}
    for link in tables["links"]:
        target = link["target_session"]
        if link["target_record"] is not None:
            typ = records.get((target, link["target_record"]))
            link["resolved"] = typ == "inference" if link["kind"] == "inference" else typ is not None
        else:
            link["resolved"] = target in seen
    output.parent.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix=".asr-tables-", dir=output.parent))
    scratch.chmod(0o700)
    try:
        for name, schema in SCHEMAS.items():
            try:
                table = pa.Table.from_pylist(tables[name], schema=schema)
                pq.write_table(table, scratch / (name + ".parquet"), compression="zstd")
                (scratch / (name + ".parquet")).chmod(0o600)
            except (pa.ArrowException, OverflowError, ValueError):
                raise ExportError("unrepresentable-column-value") from None
        manifest = dict(schema_version=1, sessions=len(seen),
                        tables={name: len(rows) for name, rows in tables.items()})
        (scratch / "manifest.json").write_text(dumps(manifest) + "\n", encoding="utf-8")
        (scratch / "manifest.json").chmod(0o600)
        scratch.rename(output)
    finally:
        if scratch.exists():
            shutil.rmtree(scratch)
    return manifest
