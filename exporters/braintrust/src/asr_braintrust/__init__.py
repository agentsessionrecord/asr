"""Braintrust v1 project log and dataset insert bodies, SDK 0.3.9."""

from decimal import Decimal

from asr_evals.cli import run
from asr_evals.jsonio import dumps
from asr_evals.model import observations, record_view
from asr_evals.reader import CORE, stable_id


def export(sessions, dataset, args):
    events = []
    for session in sessions:
        items = observations(session, args.include_content, args.inference_ts, args.tool_times)
        root_id = items[0]["id"]
        for item in items:
            event = {"id": stable_id(item["reference"]), "span_id": item["id"], "root_span_id": root_id,
                     "span_attributes": {"name": item["name"], "type": "llm" if item["kind"] == "inference" else "task" if item["kind"] == "session" else "tool"},
                     "metadata": item["metadata"]}
            if item.get("parent_id"):
                event["span_parents"] = [item["parent_id"]]
            for key in ("input", "output"):
                if key in item:
                    event[key] = item[key]
            metrics = {}
            if item["interval"]:
                metrics.update({key: Decimal(item["interval"][key]) / 1_000_000_000 for key in ("start", "end")})
            if item["kind"] == "inference":
                record = item["record"]
                usage = record.get("usage", {})
                for source, target in (("inputTokens", "prompt_tokens"), ("outputTokens", "completion_tokens")):
                    if source in usage:
                        metrics[target] = usage[source]
                if "inputTokens" in usage and "outputTokens" in usage:
                    metrics["tokens"] = usage["inputTokens"] + usage["outputTokens"]
                cost = record.get("cost")
                if cost is not None and cost["currency"] == "USD":
                    metrics["cost"] = cost["amount"]
            if metrics:
                event["metrics"] = metrics
            if item.get("error"):
                event["error"] = "asr.recorded_error"
            events.append(event)
        for record in session.records:
            if not session.original(record) or record["type"] not in CORE or record["type"] in ("inference", "tool_call"):
                continue
            reference = session.cite(record)
            events.append({"id": stable_id(reference), "span_id": stable_id(reference, 8),
                           "root_span_id": root_id, "span_parents": [root_id],
                           "span_attributes": {"name": "asr." + record["type"], "type": "function"},
                           "metadata": {"asr.event": record_view(session, record, args.include_content)}})
    return {"project-logs.json": dumps({"events": events}) + "\n",
            "dataset-insert.json": dumps({"events": dataset}) + "\n"}


def main():
    return run("asr-braintrust", export)
