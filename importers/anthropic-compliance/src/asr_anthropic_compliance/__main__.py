import argparse
from pathlib import Path

from . import import_pages


def main():
    parser = argparse.ArgumentParser(description="Convert saved oldest-first Claude Code Compliance transcript pages.")
    parser.add_argument("pages", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--namespace")
    args = parser.parse_args()
    try:
        import_pages(args.pages, args.output, namespace=args.namespace)
    except (ValueError, OSError, TypeError):
        parser.exit(2, "Import failed. Check the documented source profile and output path.\n")


if __name__ == "__main__":
    main()
