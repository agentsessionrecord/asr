import argparse
from pathlib import Path
import sys

from .bundle import export, mapping, read_jsonl, verify_bundle
from .reader import SearchError, dumps, loads, valid_index
from .transport import LocalHTTP, load_qdrant, load_search


def main(argv=None):
    parser = argparse.ArgumentParser(description="Export ASR search documents and load local databases.")
    sub = parser.add_subparsers(dest="command", required=True)
    output = sub.add_parser("export", help="Create an offline search bundle")
    output.add_argument("sessions", nargs="+", type=Path)
    output.add_argument("--output", required=True, type=Path)
    output.add_argument("--index", default="asr-records")
    output.add_argument("--chunk-size", type=int, default=1200)
    output.add_argument("--overlap", type=int, default=100)
    output.add_argument("--embedding-command-json", help="Explicit argv array, never a shell command")
    output.add_argument("--dimensions", type=int)
    output.add_argument("--embedding-model")
    for name in ("load-search", "load-qdrant"):
        loader = sub.add_parser(name, help="Load a verified bundle into a loopback endpoint")
        loader.add_argument("bundle", type=Path)
        loader.add_argument("--endpoint", required=True)
        loader.add_argument("--batch-size", type=int, default=64)
        if name == "load-qdrant":
            loader.add_argument("--collection", default="asr-chunks")
    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            command = loads(args.embedding_command_json) if args.embedding_command_json is not None else None
            result = export(args.sessions, args.output, args.index, args.chunk_size, args.overlap,
                            command, args.dimensions, args.embedding_model)
            print(dumps({"counts": result["counts"], "reader_issue_count": len(result["reader_issues"])}))
        else:
            if not 1 <= args.batch_size <= 1000:
                raise SearchError("batch_size_out_of_range")
            client = LocalHTTP(args.endpoint)
            manifest = verify_bundle(args.bundle)
            if args.command == "load-search":
                count = load_search(client, manifest["index"], mapping(),
                                    read_jsonl(args.bundle / "documents.jsonl"), args.batch_size)
            else:
                valid_index(args.collection)
                if "embedding" not in manifest:
                    raise SearchError("bundle_has_no_embeddings")
                count = load_qdrant(client, args.collection, manifest["embedding"]["dimensions"],
                                    read_jsonl(args.bundle / "chunks.jsonl"), args.batch_size)
            print(dumps({"loaded": count}))
        return 0
    except (SearchError, OSError, ValueError, KeyError, TypeError, RecursionError) as error:
        code = str(error) if isinstance(error, SearchError) else "invalid_input_or_io_failure"
        print("asr-search: " + code, file=sys.stderr)
        return 1
