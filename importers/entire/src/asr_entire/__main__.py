import argparse
from pathlib import Path

from . import import_repository


def main():
    parser = argparse.ArgumentParser(description="Read the local entire/checkpoints/v1 branch without fetching or checking it out.")
    parser.add_argument("repository", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--namespace")
    args = parser.parse_args()
    try:
        outputs = import_repository(args.repository, args.output_dir, namespace=args.namespace)
        print(f"Imported {len(outputs)} session(s).")
    except (ValueError, OSError, TypeError, UnicodeError):
        parser.exit(2, "Import failed. Check the local branch, checkpoint layout, and output path.\n")


if __name__ == "__main__":
    main()
