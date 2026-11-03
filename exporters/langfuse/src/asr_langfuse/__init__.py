"""Langfuse public ingestion API as represented by Python SDK 3.8.1."""

from datetime import datetime, timezone
from hashlib import sha256
from uuid import UUID

from asr_evals.cli import run
from asr_evals.jsonio import dumps
from asr_evals.model import iso_ns, observations, record_view, timestamp_ns
from asr_evals.reader import CORE, stable_id


def export(sessions, dataset, args):
    batch, omitted = [], []
    created_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")

    def event(kind, reference, body):
        event_id = str(UUID(bytes=sha256((reference + ":" + kind).encode()).digest()[:16], version=4))
        batch.append({"id": event_id, "type": kind, "timestamp": created_at,
                      "metadata": {"asr.timestamp_basis": "export_envelope_creation"}, "body": body})

    for session in sessions:
        trace_id = stable_id(session.ref)
        trace = {"id": trace_id, "name": "asr.session", "sessionId": session.ref,
                 "public": False, "metadata": {"asr.session": session.ref, "asr.missing": sorted(session.missing)}}
        start = timestamp_ns(session.header.get("startedAt"))
        if start is not None:
            trace["timestamp"] = iso_ns(start)
        else:
            trace["metadata"]["asr.timestamp_unknown"] = True
        event("trace-create", session.ref, trace)
        items = observations(session, args.include_content, args.inference_ts, args.tool_times)
        selected = {o["id"] for o in items[1:] if o["interval"] is not None}
        for item in items[1:]:
            timing = item["interval"]
            if timing is None:
                omitted.append({"reference": item["reference"], "reason": "timing_unknown", "retained_in": "audit.json"})
                continue
            body = {"id": item["id"], "traceId": trace_id, "name": item["name"], "metadata": item["metadata"],
                    "startTime": iso_ns(timing["start"]), "endTime": iso_ns(timing["end"])}
            if item.get("parent_id") in selected:
                body["parentObservationId"] = item["parent_id"]
            for key in ("input", "output"):
                if key in item:
                    body[key] = item[key]
            if item.get("error"):
                body["level"] = "ERROR"
                body["statusMessage"] = "Recorded ASR error or failed tool outcome"
            record = item["record"]
            kind = "span-create"
            if item["kind"] == "inference":
                kind = "generation-create"
                if "id" in record.get("model", {}):
                    body["model"] = record["model"]["id"]
                if "settings" in record:
                    body["modelParameters"] = record["settings"]
                usage = record.get("usage", {})
                details = {target: usage[source] for source, target in (("inputTokens", "input"), ("outputTokens", "output")) if source in usage}
                if len(details) == 2:
                    details["total"] = details["input"] + details["output"]
                if details:
                    body["usageDetails"] = details
                cost = record.get("cost")
                if cost is not None and cost["currency"] == "USD":
                    body["costDetails"] = {"total": cost["amount"]}
            event(kind, item["reference"], body)
        for record in session.records:
            if not session.original(record) or record["type"] not in CORE or record["type"] in ("tool_call", "inference", "tool_result"):
                continue
            stamp = timestamp_ns(record.get("ts"))
            if stamp is None:
                continue
            event("event-create", session.cite(record), {
                "id": stable_id(session.cite(record), 8), "traceId": trace_id,
                "name": "asr." + record["type"], "startTime": iso_ns(stamp),
                "metadata": record_view(session, record, args.include_content)})
    items = [{"id": row["id"], "datasetName": args.dataset_name, "input": row["input"],
              "expectedOutput": row["expected"], "metadata": row["metadata"]} for row in dataset]
    return {"ingestion.json": dumps({"batch": batch}) + "\n",
            "dataset-items.jsonl": "".join(dumps(item) + "\n" for item in items),
            "omitted.json": dumps(omitted) + "\n"}


def main():
    return run("asr-langfuse", export)
