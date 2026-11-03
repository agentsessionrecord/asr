"""Round-trip synthetic OTLP JSON through a disposable local Collector container."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from asr_otel import export_sessions, read_session
from asr_otel.transport import DeliveryError, send

IMAGE = ("otel/opentelemetry-collector-contrib:0.139.0@"
         "sha256:faf125d656fa47cea568b2f3b4494efd2525083bc75c1e96038bc23f05cd68fd")
FIXTURES = Path(__file__).parent / "fixtures"


def canonical(value):
    """An omitted protobuf repeated field is equivalent to an empty array."""
    if isinstance(value, list):
        return [canonical(v) for v in value]
    if isinstance(value, dict):
        result = {key: canonical(member) for key, member in value.items()}
        if "arrayValue" in result:
            result["arrayValue"].setdefault("values", [])
        return result
    return value


def run(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sudo", action="store_true", help="run Docker through sudo -n")
    args = parser.parse_args(argv)
    docker = ["sudo", "-n", "docker"] if args.sudo else ["docker"]

    def command(*parts):
        result = subprocess.run([*docker, *parts], text=True, capture_output=True)
        if result.returncode:
            raise RuntimeError("docker_" + parts[0] + "_failed")
        return result.stdout.strip()

    with tempfile.TemporaryDirectory(prefix="asr-otel-collector-") as directory:
        scratch = Path(directory)
        config = scratch / "collector.yaml"
        config.write_text("""receivers:
  otlp:
    protocols:
      http:
        endpoint: 0.0.0.0:4318
exporters:
  file/traces:
    path: /work/traces.jsonl
    flush_interval: 100ms
  file/logs:
    path: /work/logs.jsonl
    flush_interval: 100ms
service:
  telemetry:
    logs:
      level: error
    metrics:
      level: none
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [file/traces]
    logs:
      receivers: [otlp]
      exporters: [file/logs]
""")
        container = None
        try:
            container = command("run", "--detach", "--rm", "--network", "bridge",
                                "--user", f"{os.getuid()}:{os.getgid()}",
                                "--publish", "127.0.0.1::4318", "--volume", f"{scratch}:/work",
                                IMAGE, "--config=/work/collector.yaml")
            port = command("port", container, "4318/tcp").rsplit(":", 1)[1]
            endpoint = "http://127.0.0.1:" + port
            result = export_sessions([read_session(FIXTURES / "session.jsonl"), read_session(FIXTURES / "child.jsonl")],
                                     json.loads((FIXTURES / "contracts.json").read_text()))
            # Empty readiness requests cannot duplicate the fixture export.
            empty = export_sessions([])
            empty.traces = {"resourceSpans": [{"scopeSpans": []}]}
            deadline = time.monotonic() + 30
            while True:
                try:
                    send(empty, endpoint, timeout=1)
                    break
                except DeliveryError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("collector_not_ready") from None
                    time.sleep(.1)
            send(result, endpoint)
            deadline = time.monotonic() + 10
            while True:
                documents = {}
                try:
                    for signal in ("traces", "logs"):
                        documents[signal] = [json.loads(line) for line in (scratch / (signal + ".jsonl")).read_text().splitlines()]
                    stored_spans = [span for d in documents["traces"] for r in d.get("resourceSpans", [])
                                    for scope in r.get("scopeSpans", []) for span in scope.get("spans", [])]
                    stored_logs = [log for d in documents["logs"] for r in d.get("resourceLogs", [])
                                   for scope in r.get("scopeLogs", []) for log in scope.get("logRecords", [])]
                    if len(stored_spans) == result.report["spans"] and len(stored_logs) == result.report["logs"]:
                        break
                except (FileNotFoundError, json.JSONDecodeError):
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError("collector_roundtrip_incomplete")
                time.sleep(.1)
            expected_spans = result.traces["resourceSpans"][0]["scopeSpans"][0]["spans"]
            expected = {s["spanId"]: s for s in expected_spans}
            for span in stored_spans:
                original = expected[span["spanId"]]
                assert span["traceId"] == original["traceId"]
                assert span["startTimeUnixNano"] == original["startTimeUnixNano"]
                assert span["endTimeUnixNano"] == original["endTimeUnixNano"]
                assert canonical(span["attributes"]) == canonical(original["attributes"])
                assert canonical(span.get("links", [])) == canonical(original.get("links", []))
                assert canonical(span.get("events", [])) == canonical(original.get("events", []))
            for stored, original in zip(stored_logs, result.logs["resourceLogs"][0]["scopeLogs"][0]["logRecords"]):
                assert canonical(stored["attributes"]) == canonical(original["attributes"])
                assert stored.get("timeUnixNano") == original.get("timeUnixNano")
                assert stored["traceId"] == original["traceId"]
                assert stored.get("spanId") == original.get("spanId")
                assert stored["body"] == original["body"]
            print(f"collector={IMAGE} spans={len(stored_spans)} logs={len(stored_logs)} "
                  "ids=passed timestamps=passed attributes=passed links=passed events=passed")
        finally:
            if container:
                # Address only the container created by this invocation.
                command("stop", "--time", "5", container)
                remaining = command("ps", "--all", "--quiet", "--filter", "id=" + container)
                if remaining:
                    raise RuntimeError("collector_cleanup_failed")
                print("collector_cleanup=passed")


if __name__ == "__main__":
    run()
