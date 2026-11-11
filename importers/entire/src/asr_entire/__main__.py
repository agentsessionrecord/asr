import argparse
from pathlib import Path

from . import import_repository


def main():
    parser = argparse.ArgumentParser(description="Read local Entire checkpoints from Git objects without fetching or checking them out.")
    parser.add_argument("repository", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--namespace")
    parser.add_argument("--transcript", choices=("auto", "normalized", "full"), default="auto",
                        help="normalized reads transcript.jsonl, full reads the Claude Code or Codex full.jsonl")
    args = parser.parse_args()
    try:
        outputs = import_repository(args.repository, args.output_dir, namespace=args.namespace, transcript=args.transcript)
        print(f"Imported {len(outputs)} session(s).")
    except (ValueError, OSError, TypeError, UnicodeError):
        parser.exit(2, "Import failed. Check the local checkpoints, their layout, and the output path.\n")


if __name__ == "__main__":
    main()
