import argparse
import os
from pathlib import Path
import sys
import tempfile

from .exporter import export_sessions
from .reader import exact_json, parse_json, read_session
from .transport import DeliveryError, local_endpoint, send


def write_private(path, document):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write((exact_json(document) + "\n").encode("utf-8"))
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Export ASR 0.1 to local OTLP JSON traces and logs.")
    parser.add_argument("sessions", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True, help="directory for traces.json, logs.json and report.json")
    parser.add_argument("--contracts", type=Path, help="documented producer timestamp and semantic contracts")
    parser.add_argument("--include-content", action="store_true", help="include recorded ASR JSON, including tool arguments and output")
    parser.add_argument("--include-identity", action="store_true", help="include recorded personal identity fields")
    parser.add_argument("--user-name-kind", choices=("short", "full"), help="meaning of the recorded session user.name")
    parser.add_argument("--endpoint", help="numeric loopback OTLP/HTTP base URL, such as http://127.0.0.1:4318")
    parser.add_argument("--timeout", type=float, default=10, help="delivery timeout in seconds")
    args = parser.parse_args(argv)
    if not 0 < args.timeout <= 300:
        parser.error("timeout must be greater than zero and at most 300 seconds")
    if args.user_name_kind and not args.include_identity:
        parser.error("user-name-kind requires include-identity")
    try:
        if args.endpoint:
            local_endpoint(args.endpoint)
        contracts = parse_json(args.contracts.read_text(encoding="utf-8")) if args.contracts else None
        result = export_sessions([read_session(p) for p in args.sessions], contracts,
                                 include_content=args.include_content, include_identity=args.include_identity,
                                 user_name_kind=args.user_name_kind)
        args.output.mkdir(mode=0o700, parents=True, exist_ok=True)
        # A user-selected output directory must not overwrite one of the input streams.
        inputs = {p.resolve() for p in args.sessions}
        if args.contracts:
            inputs.add(args.contracts.resolve())
        targets = [args.output / name for name in ("traces.json", "logs.json", "report.json")]
        if any(p.resolve() in inputs for p in targets):
            raise ValueError("output_overlaps_input")
        for path, document in zip(targets, (result.traces, result.logs, result.report)):
            write_private(path, document)
        if args.endpoint:
            send(result, args.endpoint, args.timeout)
        print(f"sessions={result.report['sessions']} spans={result.report['spans']} "
              f"logs={result.report['logs']} diagnostics={len(result.report['diagnostics'])}")
        return 0
    except (OSError, ValueError, RecursionError) as error:
        # Source lines and collector response bodies can contain private text.
        code = str(error) if isinstance(error, DeliveryError) else (
            str(error) if type(error) is ValueError and str(error).replace("_", "").isalnum() else "export_failed")
        print("asr-otel: " + code, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
