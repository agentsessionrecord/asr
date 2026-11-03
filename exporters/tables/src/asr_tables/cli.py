"""Command line entry point. Diagnostics contain positions and codes, never source text."""

import argparse
from pathlib import Path
import sys

from .export import export
from .loaders import clickhouse_ddl, load_duckdb
from .reader import ExportError, dumps


def main(argv=None):
    parser = argparse.ArgumentParser(prog="asr-tables")
    commands = parser.add_subparsers(dest="command", required=True)
    convert = commands.add_parser("export", help="Write a new Parquet dataset")
    convert.add_argument("inputs", nargs="+", type=Path)
    convert.add_argument("--output", required=True, type=Path)
    load = commands.add_parser("duckdb", help="Replace fixed ASR tables in a local DuckDB database")
    load.add_argument("dataset", type=Path)
    load.add_argument("database", type=Path)
    commands.add_parser("clickhouse-ddl", help="Print empty-table DDL for a local ClickHouse database")
    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            result = export(args.inputs, args.output)
            print(dumps(result))
            if result["tables"]["diagnostics"]:
                print("diagnostics-recorded: inspect diagnostics.parquet", file=sys.stderr)
            return 0
        if args.command == "duckdb":
            load_duckdb(args.dataset, args.database)
            return 0
        print(clickhouse_ddl(), end="")
        return 0
    except ExportError as error:
        print(str(error), file=sys.stderr)
    except Exception:
        print("operation-failed", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
