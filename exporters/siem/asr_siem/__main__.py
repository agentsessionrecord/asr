"""Write local files only."""

import argparse
import os
from pathlib import Path
import sys

from .mapping import convert
from .outputs import encode_output
from .reader import json_text, read_session


def main(argv=None):
    parser = argparse.ArgumentParser(description="Export ASR to local OCSF or SIEM request files.")
    parser.add_argument("session", type=Path)
    parser.add_argument("--target", choices=("ocsf", "splunk", "datadog", "elastic"), default="ocsf")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", type=Path, help="Defaults to OUTPUT.report.json")
    parser.add_argument("--index", default="asr-audit")
    parser.add_argument("--include-content", action="store_true")
    parser.add_argument("--observed-at", help="Explicit collection time for records without ts. Marked as observation time.")
    parser.add_argument("--device-uid", help="Known source device identity supplied by the collector.")
    args = parser.parse_args(argv)
    report_path = args.report or Path(str(args.output) + ".report.json")
    try:
        paths = (args.session, args.output, report_path)
        if len({p.resolve() for p in paths}) != 3 or any(p.is_symlink() for p in paths[1:]):
            raise ValueError("output_alias")
        result = convert(read_session(args.session), include_content=args.include_content,
                         observed_at=args.observed_at, device_uid=args.device_uid)
        body = encode_output(result.events, args.target, index=args.index)
        created = []
        try:
            for path, text in ((args.output, body), (report_path, json_text(result.report) + "\n")):
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                created.append(path)
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                    stream.write(text)
        except OSError:
            for path in created:
                path.unlink(missing_ok=True)
            raise
    except (OSError, ValueError, TypeError):
        print("export_failed: check framing, options and unused writable output paths", file=sys.stderr)
        return 1
    print(f"{len(result.events)} events, {len(result.report['untimed_events'])} untimed, {len(result.report['diagnostics'])} diagnostics")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
