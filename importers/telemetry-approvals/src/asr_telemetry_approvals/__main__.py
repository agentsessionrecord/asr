from __future__ import annotations

import argparse
import json
import sys

from .importer import import_approvals


def main() -> int:
    parser = argparse.ArgumentParser(description="Add approval telemetry to a new ASR file")
    parser.add_argument("source", help="Existing ASR session")
    parser.add_argument("--telemetry", action="append", required=True, help="OTLP JSON or console exporter file. Repeat in source order")
    parser.add_argument("--output", required=True, help="New ASR file. Existing files are refused")
    args = parser.parse_args()
    try:
        summary = import_approvals(args.source, args.telemetry, args.output)
    except (OSError, ValueError, KeyError, TypeError) as error:
        # Exception messages from source parsers can contain private values.
        print(f"import failed ({type(error).__name__}). Check input framing, versions and output path.", file=sys.stderr)
        return 1
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
