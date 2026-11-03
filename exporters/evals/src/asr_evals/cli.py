"""File-only command plumbing. No credentials, sockets or command execution."""

import argparse
import os
from pathlib import Path

from .dataset import rows
from .jsonio import dumps
from .model import audit
from .reader import load_sessions, read_annotations


def run(name, exporter=None):
    parser = argparse.ArgumentParser(prog=name, description="Export ASR 0.1 to new offline files.")
    parser.add_argument("sessions", nargs="+")
    parser.add_argument("--output", required=True, help="New directory. Existing paths are refused.")
    parser.add_argument("--annotations", action="append", default=[])
    parser.add_argument("--include-content", action="store_true")
    parser.add_argument("--dataset-name", default="asr-evals")
    parser.add_argument("--test-tool", action="append", default=[])
    parser.add_argument("--inference-ts", choices=("unknown", "start", "end"), default="unknown",
                        help="Producer timestamp contract. Never inferred from nearby records.")
    parser.add_argument("--tool-times", action="store_true", help="Assert call ts is start and result ts is completion.")
    args = parser.parse_args()
    try:
        sessions = load_sessions(args.sessions)
        annotations, annotation_diagnostics = read_annotations(args.annotations)
        dataset = rows(sessions, annotations, args.include_content, args.test_tool)
        evidence = audit(sessions, annotations, args.include_content)
        evidence["annotation_diagnostics"] = annotation_diagnostics
        files = {"dataset.jsonl": "".join(dumps(row) + "\n" for row in dataset), "audit.json": dumps(evidence) + "\n"}
        if exporter:
            files.update(exporter(sessions, dataset, args))
        # Never overwrite source files or an earlier export.
        destination = Path(args.output)
        destination.mkdir(mode=0o700, parents=False, exist_ok=False)
        for name, body in files.items():
            if Path(name).name != name:
                raise ValueError("invalid_artifact_name")
            fd = os.open(destination / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(body if isinstance(body, bytes) else body.encode("utf-8"))
        print(f"sessions={len(sessions)} rows={len(dataset)} files={len(files)} diagnostics="
              f"{sum(len(s.diagnostics) for s in sessions) + len(annotation_diagnostics)}")
    except (OSError, ValueError, KeyError, TypeError) as error:
        # Input content and private source paths never appear in error output.
        print("export_failed:" + (str(error) if isinstance(error, ValueError) and str(error) in {
            "missing_header", "unsupported_or_missing_header", "invalid_session_identity", "conflicting_session_exports"
        } else type(error).__name__))
        return 1
    return 0


def main():
    return run("asr-evals")
