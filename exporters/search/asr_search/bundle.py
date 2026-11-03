"""Portable projections, with hashes to reject partial or changed bundles."""

from collections import Counter
import hashlib
from pathlib import Path
import shutil
import tempfile

from .documents import Catalog, USAGE_FIELDS, chunks, documents
from .reader import SearchError, dumps, loads, read_stream, valid_index
from .transport import embed


def mapping():
    keyword = {"type": "keyword", "ignore_above": 8191}
    properties = {key: dict(keyword) for key in (
        "document_id", "doc_kind", "session_ref", "citation", "record_id", "record_type", "source_sha256",
        "agent", "known_missing", "unresolved_refs", "turn_id", "inference_id", "call_id", "role", "author",
        "origin", "tool_name", "tool_kind", "status", "action", "evidence", "decision", "decider",
        "commit_prefix", "paths", "resolved_paths", "commits", "model_served", "model_requested", "model_provider",
        "paired_call", "paired_result", "call_outcome", "pairing", "related_refs", "gap_reason")}
    for key in ("schema_version", "position", "gap_count", "gap_records"):
        properties[key] = {"type": "long"}
    for key in ("copied", "credit_eligible", "truncated"):
        properties[key] = {"type": "boolean"}
    for key in ("event_time", "current_endedAt"):
        properties[key] = {"type": "date", "format": "strict_date_optional_time_nanos"}
    for key in ("text", "current_title"):
        properties[key] = {"type": "text"}
    for key in ("raw_json", "agent_settings_json", "effective_input_json", "cost_json", "repos_json",
                "session_usage_json", "session_cost_json", "session_tools_json", "final_agent_settings_json"):
        properties[key] = {"type": "text", "index": False}
    for key in ("text_fields", "reader_issues", "relationships"):
        properties[key] = {"type": "object", "enabled": False}
    properties["usage"] = {"type": "object", "dynamic": "strict",
                           "properties": {field: {"type": "long"} for field in USAGE_FIELDS}}
    return {"settings": {"number_of_shards": 1, "number_of_replicas": 0},
            "mappings": {"dynamic": "strict", "properties": properties}}


def _hash(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def export(paths, destination, index="asr-records", chunk_size=1200, overlap=100,
           embedding_command=None, dimensions=None, embedding_model=None, embedding_batch=64):
    valid_index(index)
    if chunk_size < 1 or overlap < 0 or overlap >= chunk_size:
        raise SearchError("invalid_chunk_size_or_overlap")
    if (embedding_command is not None and (not dimensions or not 1 <= dimensions <= 65536 or not embedding_model)
            or embedding_command is None and (dimensions is not None or embedding_model is not None)):
        raise SearchError("embedding_requires_command_dimensions_and_model")
    destination = Path(destination)
    if destination.exists():
        raise SearchError("output_directory_already_exists")
    catalog = Catalog()
    inputs = []
    for path in paths:
        stream = read_stream(path)
        catalog.add(stream)
        inputs.append((Path(path), stream.ref))
    if not inputs:
        raise SearchError("no_input_sessions")
    destination.parent.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix=".asr-search-", dir=destination.parent))
    scratch.chmod(0o700)
    counts = Counter(sessions=len(inputs))
    issues = []
    try:
        (scratch / "mapping.json").write_text(dumps(mapping()) + "\n", encoding="utf-8")
        with ((scratch / "documents.jsonl").open("w", encoding="utf-8") as doc_file,
              (scratch / "bulk.ndjson").open("w", encoding="utf-8") as bulk_file,
              (scratch / "chunks.jsonl").open("w", encoding="utf-8") as chunk_file):
            pending = []

            def flush():
                if not pending:
                    return
                if embedding_command is not None:
                    vectors = embed(embedding_command, [item["text"] for item in pending], dimensions)
                    for item, vector in zip(pending, vectors, strict=True):
                        item["vector"] = vector
                        item["embedding_model"] = embedding_model
                for item in pending:
                    chunk_file.write(dumps(item) + "\n")
                pending.clear()

            for path, ref in inputs:
                stream = read_stream(path)
                if stream.sha256 != catalog.digests[ref] or stream.ref != ref:
                    raise SearchError("input_changed_during_export")
                issues.extend({"session_ref": ref, **issue} for issue in stream.issues)
                for doc in documents(stream, catalog):
                    doc_file.write(dumps(doc) + "\n")
                    bulk_file.write(dumps({"index": {"_index": index, "_id": doc["document_id"]}}) + "\n")
                    bulk_file.write(dumps(doc) + "\n")
                    counts["documents"] += 1
                    counts["gaps"] += doc["record_type"] == "gap"
                    counts["unresolved_references"] += len(doc["unresolved_refs"])
                    for chunk in chunks(doc, chunk_size, overlap):
                        counts["chunks"] += 1
                        pending.append(chunk)
                        if len(pending) >= embedding_batch:
                            flush()
            flush()
        manifest = {"schema_version": 1, "index": index, "counts": dict(counts), "reader_issues": issues,
                    "chunk_size": chunk_size, "overlap": overlap,
                    "inputs": [{"session_ref": ref, "sha256": catalog.digests[ref]} for _, ref in inputs],
                    "files": {name: _hash(scratch / name) for name in (
                        "mapping.json", "documents.jsonl", "bulk.ndjson", "chunks.jsonl")}}
        if embedding_command is not None:
            manifest["embedding"] = {"dimensions": dimensions, "model": embedding_model, "distance": "Cosine"}
        (scratch / "manifest.json").write_text(dumps(manifest) + "\n", encoding="utf-8")
        scratch.rename(destination)
        return manifest
    finally:
        if scratch.exists():
            shutil.rmtree(scratch)


def verify_bundle(directory):
    directory = Path(directory)
    manifest = loads((directory / "manifest.json").read_bytes())
    if manifest.get("schema_version") != 1:
        raise SearchError("unsupported_bundle_version")
    valid_index(manifest["index"])
    for name in ("mapping.json", "documents.jsonl", "bulk.ndjson", "chunks.jsonl"):
        if manifest.get("files", {}).get(name) != _hash(directory / name):
            raise SearchError("bundle_integrity_failure")
    if loads((directory / "mapping.json").read_bytes()) != mapping():
        raise SearchError("bundle_mapping_differs")
    return manifest


def read_jsonl(path):
    with Path(path).open("r", encoding="utf-8") as source:
        for line in source:
            if not line.endswith("\n"):
                raise SearchError("incomplete_bundle_file")
            yield loads(line)
