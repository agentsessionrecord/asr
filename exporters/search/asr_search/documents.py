"""Index recorded facts and conservative joins, without deriving blame."""

from collections import defaultdict
from copy import deepcopy
import hashlib
import ntpath
import posixpath
import uuid

from .reader import SearchError, citation, dumps


USAGE_FIELDS = ("inputTokens", "cacheReadTokens", "cacheWriteTokens", "outputTokens", "reasoningTokens")


class Catalog:
    def __init__(self):
        self.records = {}
        self.digests = {}
        self.edges = {}

    def add(self, stream):
        if stream.ref in self.records:
            raise SearchError("duplicate_session_identity")
        self.records[stream.ref] = {r.record["id"] for r in stream.rows}
        self.digests[stream.ref] = stream.sha256
        parent = stream.header.get("parent", {})
        if parent.get("session") and parent.get("kind") in ("subagent", "fork", "continues"):
            self._edge(parent["session"], stream.ref, parent["kind"],
                       citation(stream.ref, stream.header["id"]), parent.get("callId"))
        for row in stream.rows:
            record = row.record
            if record["type"] not in ("tool_call", "tool_result"):
                continue
            child = record.get("subagent", {}).get("session")
            if child:
                self._edge(stream.ref, child, "subagent", citation(stream.ref, record["id"]),
                           record.get("callId"))

    def _edge(self, parent, child, kind, evidence, call_id):
        edge = self.edges.setdefault((parent, child, kind),
                                     {"parent": parent, "child": child, "kind": kind,
                                      "evidence": [], "call_ids": []})
        edge["evidence"].append(evidence)
        if call_id is not None and call_id not in edge["call_ids"]:
            edge["call_ids"].append(call_id)

    def resolves(self, ref):
        session, separator, _ = ref.partition("#")
        if session not in self.records:
            return False
        if separator:
            return any(citation(session, record_id) == ref for record_id in self.records[session])
        return True

    def relationships(self, ref):
        return [deepcopy(edge) for key, edge in self.edges.items() if ref in key[:2]]


def update_settings(current, update):
    current = deepcopy(current)
    if any(k in update and update[k] != current.get(k) for k in ("mode", "approval", "sandbox")) and "asks" not in update:
        current.pop("asks", None)
    for key, value in update.items():
        if value is None:
            current.pop(key, None)
        elif key == "modelSettings":
            model = current.setdefault(key, {})
            for field, setting in value.items():
                if setting is None:
                    model.pop(field, None)
                else:
                    model[field] = setting
        else:
            current[key] = deepcopy(value)
    return current


def _parts(record):
    for index, part in enumerate(record.get("content", [])):
        if not isinstance(part, dict):
            continue
        author = part.get("author", record.get("author"))
        origin = part.get("origin", record.get("origin"))
        prefix = f"content.{index}"
        if part.get("type") == "text" and isinstance(part.get("text"), str):
            yield prefix + ".text", part["text"], author, origin
        elif part.get("type") == "reasoning" and part.get("visibility") != "encrypted":
            if isinstance(part.get("text"), str):
                yield prefix + ".text", part["text"], author, origin
            for n, text in enumerate(part.get("summary", [])):
                if isinstance(text, str):
                    yield f"{prefix}.summary.{n}", text, author, origin
        elif part.get("type") == "resource" and isinstance(part.get("resource"), dict):
            text = part["resource"].get("text")
            if isinstance(text, str):
                yield prefix + ".resource.text", text, author, origin


def text_fields(record):
    kind = record["type"]
    if kind in ("message", "tool_result"):
        yield from _parts(record)
    fields = {
        "session": ("title",), "session_info": ("title",),
        "tool_call": ("inputText",), "tool_result": ("inputText",),
        "file_change": ("patch",), "vcs": ("subject",),
        "gap": ("detail",), "approval": ("subject",),
    }
    for field in fields.get(kind, ()):
        if isinstance(record.get(field), str):
            yield field, record[field], None, None
    if kind in ("tool_call", "tool_result") and "input" in record:
        yield "input", dumps(record["input"]), None, None
    if kind == "tool_result":
        for field in ("command", "stdout", "stderr", "output"):
            value = record.get("exec", {}).get(field)
            if isinstance(value, (str, list)):
                yield "exec." + field, value if isinstance(value, str) else dumps(value), None, None
    if kind == "file_change":
        for field in ("before", "after"):
            value = record.get(field, {}).get("text")
            if isinstance(value, str):
                yield field + ".text", value, None, None
        for n, edit in enumerate(record.get("edits", [])):
            for field in ("oldText", "newText"):
                if isinstance(edit.get(field), str):
                    yield f"edits.{n}.{field}", edit[field], None, None


def path_fields(record, header):
    kind = record["type"]
    paths = []
    if kind == "file_change":
        paths = [record[k] for k in ("path", "oldPath") if k in record]
    elif kind == "tool_call":
        paths = [loc["path"] for loc in record.get("locations", []) if "path" in loc]
    elif kind == "vcs" and "repo" in record:
        paths = [record["repo"]]
    elif kind in ("session", "session_info"):
        paths = [repo["path"] for repo in record.get("repos", []) if "path" in repo]
        if kind == "session" and "cwd" in record:
            paths.append(record["cwd"])
    paths = list(dict.fromkeys(p for p in paths if isinstance(p, str)))
    resolved = []
    cwd = header.get("cwd")
    for path in paths:
        if posixpath.isabs(path) or ntpath.isabs(path):
            resolved.append(path)
        elif cwd and posixpath.isabs(cwd):
            resolved.append(posixpath.normpath(posixpath.join(cwd, path)))
        elif cwd and ntpath.isabs(cwd):
            resolved.append(ntpath.normpath(ntpath.join(cwd, path)))
    return paths, list(dict.fromkeys(resolved))


def commit_fields(record):
    if record["type"] != "vcs":
        return []
    values = [record[k] for k in ("commit", "headBefore", "headAfter") if k in record]
    values += record.get("parents", [])
    for pair in record.get("rewrites", []):
        values.extend(pair[k] for k in ("from", "to") if k in pair)
    pr = record.get("pr", {})
    values += [pr[k] for k in ("headCommit", "mergeCommit") if k in pr]
    values += pr.get("commits", [])
    return list(dict.fromkeys(values))


def documents(stream, catalog):
    header = stream.header
    calls, results = defaultdict(list), defaultdict(list)
    inferences = {r.record["id"] for r in stream.rows if r.record["type"] == "inference"}
    missing = set()
    for row in stream.rows:
        record = row.record
        if record["type"] in ("session", "session_info"):
            missing.update(record.get("missing", []))
        if record["type"] == "tool_call":
            calls[record["callId"]].append(record)
        elif record["type"] == "tool_result" and "callId" in record:
            results[record["callId"]].append(record)
    boundary = header.get("parent", {}).get("copiedThrough")
    boundary_position = next((r.position for r in stream.rows if r.record["id"] == boundary), 0)
    settings, latest, repos = {}, {}, deepcopy(header.get("repos", []))
    settings_seen = False
    docs = []
    for row in stream.rows:
        record = row.record
        kind = record["type"]
        cite = citation(stream.ref, record["id"])
        copied = "copiedFrom" in record or (row.position > 1 and row.position <= boundary_position)
        doc = {
            "document_id": hashlib.sha256(dumps([stream.ref, record["id"]]).encode()).hexdigest(),
            "schema_version": 1, "doc_kind": "session" if kind == "session" else "record",
            "session_ref": stream.ref, "citation": cite, "record_id": record["id"],
            "record_type": kind, "position": row.position, "source_sha256": stream.sha256,
            "agent": header["agent"]["name"], "raw_json": row.raw,
            "copied": copied, "credit_eligible": kind != "session" and not copied,
            "known_missing": sorted(missing), "unresolved_refs": [],
        }
        if settings_seen:
            doc["agent_settings_json"] = dumps(settings)
        fields_by_kind = {
            "message": (("role", "role"), ("author", "author"), ("origin", "origin"), ("status", "status")),
            "tool_call": (("name", "tool_name"), ("kind", "tool_kind"), ("callId", "call_id")),
            "tool_result": (("status", "status"), ("callId", "call_id")),
            "approval": (("decision", "decision"), ("by", "decider"), ("callId", "call_id")),
            "file_change": (("status", "status"), ("callId", "call_id")),
            "vcs": (("status", "status"), ("action", "action"), ("evidence", "evidence"),
                    ("commitPrefix", "commit_prefix"), ("callId", "call_id")),
        }
        projection = (("ts", "event_time"), ("turnId", "turn_id"), ("inferenceId", "inference_id"),
                      ("truncated", "truncated")) + fields_by_kind.get(kind, ())
        for source, target in projection:
            if source in record:
                doc[target] = record[source]
        doc["paths"], doc["resolved_paths"] = path_fields(record, header)
        doc["commits"] = commit_fields(record)
        fields = list(text_fields(record))
        doc["text"] = [value for _, value, _, _ in fields]
        doc["text_fields"] = [{"field": key, "text": value,
                                **({"author": author} if author is not None else {}),
                                **({"origin": origin} if origin is not None else {})}
                               for key, value, author, origin in fields]
        if kind == "inference":
            model = record.get("model", {})
            for source, target in (("id", "model_served"), ("requested", "model_requested"),
                                   ("provider", "model_provider")):
                if source in model:
                    doc[target] = model[source]
            if "usage" in record:
                doc["usage"] = {k: v for k, v in record["usage"].items() if k in USAGE_FIELDS}
            if "cost" in record:
                doc["cost_json"] = dumps(record["cost"])
        if "inferenceId" in record and record["inferenceId"] not in inferences:
            doc["unresolved_refs"].append(citation(stream.ref, record["inferenceId"]))
        call_id = record.get("callId") if kind in ("tool_call", "tool_result", "approval", "file_change", "vcs") else None
        unique = len(calls[call_id]) == 1 if call_id is not None else False
        if kind in ("tool_call", "tool_result", "approval", "file_change", "vcs") and call_id is not None:
            if unique:
                doc["paired_call"] = citation(stream.ref, calls[call_id][0]["id"])
            else:
                doc["unresolved_refs"].append("call:" + call_id)
        if kind == "tool_call":
            doc["call_outcome"] = "unknown"
            for key in ("input", "inputText"):
                if key in record:
                    doc["effective_input_json"] = dumps(record[key])
                    break
            if unique and len(results[call_id]) == 1:
                result = results[call_id][0]
                doc["paired_result"] = citation(stream.ref, result["id"])
                outcome = result.get("status")
                if outcome in ("completed", "failed", "denied", "cancelled", "interrupted", "unknown"):
                    doc["call_outcome"] = outcome
                for key in ("input", "inputText"):
                    if key in result:
                        doc["effective_input_json"] = dumps(result[key])
                        break
            else:
                doc["unresolved_refs"].append("result:" + call_id)
        if kind in ("tool_result", "approval"):
            doc["pairing"] = "paired" if unique and (kind == "approval" or len(results[call_id]) == 1) else "unpaired"
            if doc["pairing"] == "unpaired":
                doc.pop("paired_call", None)
        refs = []
        if kind == "session":
            parent = header.get("parent", {})
            if "session" in parent:
                refs.append(parent["session"])
                if "record" in parent:
                    refs.append(citation(parent["session"], parent["record"]))
        if kind == "message" and "from" in record:
            refs.append(record["from"])
        if kind in ("tool_call", "tool_result") and "session" in record.get("subagent", {}):
            refs.append(record["subagent"]["session"])
        copy = record.get("copiedFrom", {})
        if copy:
            source = copy.get("session")
            if source:
                refs.append(citation(source, copy["record"]) if "record" in copy else source)
            else:
                doc["unresolved_refs"].append("copy_record:" + copy["record"])
        doc["related_refs"] = refs
        doc["unresolved_refs"].extend(ref for ref in refs if not catalog.resolves(ref))
        if kind == "gap":
            doc["gap_reason"] = record["reason"]
            if "count" in record:
                doc["gap_count"] = record["count"]
        if kind == "session_info":
            if "agentSettings" in record:
                settings = update_settings(settings, record["agentSettings"])
                settings_seen = True
            for key in ("title", "endedAt", "usage", "cost", "tools"):
                if key in record:
                    latest[key] = record[key]
            repos.extend(record.get("repos", []))
        docs.append(doc)
    summary = docs[0]
    summary["reader_issues"] = stream.issues
    summary["gap_records"] = sum(r.record["type"] == "gap" for r in stream.rows)
    summary["relationships"] = catalog.relationships(stream.ref)
    summary["related_refs"] = list(dict.fromkeys(
        summary["related_refs"] + [edge[k] for edge in summary["relationships"]
                                   for k in ("parent", "child") if edge[k] != stream.ref]))
    summary["unresolved_refs"] = list(dict.fromkeys(
        summary["unresolved_refs"] + [ref for ref in summary["related_refs"] if not catalog.resolves(ref)]))
    summary["repos_json"] = dumps(repos)
    for key in ("title", "endedAt"):
        if key in latest or key in header:
            summary["current_" + key] = latest.get(key, header.get(key))
    for key in ("usage", "cost", "tools"):
        if key in latest:
            summary["session_" + key + "_json"] = dumps(latest[key])
    if settings_seen:
        summary["final_agent_settings_json"] = dumps(settings)
    return docs


def chunks(doc, size=1200, overlap=100):
    if size < 1 or overlap < 0 or overlap >= size:
        raise SearchError("invalid_chunk_size_or_overlap")
    for part in doc["text_fields"]:
        text = part["text"]
        start = 0
        while start < len(text):
            end = min(start + size, len(text))
            payload = {key: doc[key] for key in (
                "session_ref", "citation", "record_id", "record_type", "position", "source_sha256",
                "copied", "credit_eligible", "known_missing", "unresolved_refs", "paths", "commits")}
            payload.update({key: doc[key] for key in ("role", "truncated", "pairing", "call_outcome") if key in doc})
            payload.update({key: part[key] for key in ("author", "origin") if key in part})
            payload.update(field=part["field"], start=start, end=end, text=text[start:end])
            name = dumps([doc["citation"], part["field"], size, overlap, start,
                          hashlib.sha256(payload["text"].encode("utf-8", errors="surrogatepass")).hexdigest()])
            payload["chunk_id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, "asr-search-v1:" + name))
            yield payload
            if end == len(text):
                break
            start = end - overlap
