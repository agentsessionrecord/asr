"""Phoenix 12.23.0 OTLP and dataset upload contracts."""

from asr_evals.cli import run
from asr_evals.jsonio import dumps
from asr_evals.model import observations, record_view, timestamp_ns
from asr_evals.reader import CORE


def attribute(key, value):
    if isinstance(value, str):
        encoded = {"stringValue": value}
    elif isinstance(value, bool):
        encoded = {"boolValue": value}
    elif isinstance(value, int) and -(2 ** 63) <= value < 2 ** 63:
        encoded = {"intValue": str(value)}
    else:
        encoded = {"stringValue": dumps(value)}
    return {"key": key, "value": encoded}


def protobuf(payload):
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
    from google.protobuf.json_format import ParseDict
    from base64 import b64encode
    from copy import deepcopy

    # Protobuf's generic JSON parser uses base64. OTLP JSON uses hex IDs.
    transport = deepcopy(payload)
    for resource in transport["resourceSpans"]:
        for scope in resource["scopeSpans"]:
            for span in scope["spans"]:
                for key in ("traceId", "spanId", "parentSpanId"):
                    if key in span:
                        span[key] = b64encode(bytes.fromhex(span[key])).decode("ascii")
    return ParseDict(transport, ExportTraceServiceRequest()).SerializeToString()


def export(sessions, dataset, args):
    spans, omitted = [], []
    for session in sessions:
        items = observations(session, args.include_content, args.inference_ts, args.tool_times)
        timed = {o["id"]: o for o in items if o["interval"] is not None}
        for item in items:
            timing = item["interval"]
            if timing is None:
                omitted.append({"reference": item["reference"], "reason": "timing_unknown", "retained_in": "audit.json"})
                continue
            kind = {"session": "AGENT", "tool_call": "TOOL", "inference": "LLM"}[item["kind"]]
            attributes = [attribute("openinference.span.kind", kind), attribute("session.id", session.ref)]
            attributes += [attribute(k, v) for k, v in item["metadata"].items()]
            record = item["record"]
            if item["kind"] == "inference":
                model = record.get("model", {})
                if "id" in model:
                    attributes.append(attribute("llm.model_name", model["id"]))
                for source, target in (("inputTokens", "llm.token_count.prompt"), ("outputTokens", "llm.token_count.completion")):
                    if source in record.get("usage", {}):
                        attributes.append(attribute(target, record["usage"][source]))
            for key in ("input", "output"):
                if key in item:
                    attributes += [attribute(key + ".value", dumps(item[key])), attribute(key + ".mime_type", "application/json")]
            span = {"traceId": item["trace_id"], "spanId": item["id"], "name": item["name"], "kind": 1,
                    "startTimeUnixNano": str(timing["start"]), "endTimeUnixNano": str(timing["end"]),
                    "attributes": attributes, "status": {"code": 2 if item.get("error") else 0}}
            parent = timed.get(item.get("parent_id"))
            if parent is not None and parent["interval"]["start"] <= timing["start"] <= timing["end"] <= parent["interval"]["end"]:
                span["parentSpanId"] = parent["id"]
            if item["kind"] == "session":
                events = []
                for event in session.records:
                    stamp = timestamp_ns(event.get("ts"))
                    if event["type"] not in CORE or not session.original(event) or stamp is None or not timing["start"] <= stamp <= timing["end"]:
                        continue
                    if event["type"] in ("inference", "tool_call"):
                        continue
                    events.append({"name": "asr." + event["type"], "timeUnixNano": str(stamp),
                                   "attributes": [attribute("asr.record", record_view(session, event, args.include_content))]})
                if events:
                    span["events"] = events
            spans.append(span)
    payload = {"resourceSpans": [{"resource": {"attributes": [attribute("openinference.project.name", args.dataset_name),
                                                           attribute("service.name", "asr-phoenix")]},
                                  "scopeSpans": [{"scope": {"name": "asr-phoenix", "version": "0.1.0"}, "spans": spans}]}]}
    upload = {"name": args.dataset_name, "action": "create",
              "inputs": [row["input"] for row in dataset], "outputs": [row["expected"] for row in dataset],
              "metadata": [dict(row["metadata"], asr_row_id=row["id"]) for row in dataset]}
    return {"traces.otlp.json": dumps(payload) + "\n", "traces.otlp.pb": protobuf(payload),
            "dataset-upload.json": dumps(upload) + "\n", "omitted.json": dumps(omitted) + "\n"}


def main():
    return run("asr-phoenix", export)
