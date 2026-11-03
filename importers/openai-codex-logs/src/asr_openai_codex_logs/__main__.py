import argparse
from pathlib import Path

from . import convert
from asr_importer_core import read_input


def main():
    parser = argparse.ArgumentParser(description="Convert one session of saved CODEX_LOG JSONL using the documented compatibility profile.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--session-id")
    parser.add_argument("--namespace")
    args = parser.parse_args()
    try:
        convert(read_input(args.input), session_id=args.session_id, namespace=args.namespace).write(args.output)
    except (ValueError, OSError, TypeError):
        parser.exit(2, "Import failed. Check the documented source profile and output path.\n")


if __name__ == "__main__":
    main()
