"""Run real database contracts in isolated, disposable Docker containers."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parents[1]
sys.path.insert(0, str(PACKAGE))

from asr_search.bundle import export, mapping, read_jsonl, verify_bundle
from asr_search.reader import SearchError, dumps, loads
from asr_search.transport import LocalHTTP, load_qdrant, load_search


IMAGES = {"opensearch": "opensearchproject/opensearch:2.19.4", "qdrant": "qdrant/qdrant:v1.15.5"}


def main():
    docker = loads(os.environ.get("ASR_SEARCH_DOCKER_JSON", '["docker"]'))
    if not isinstance(docker, list) or not docker or not all(isinstance(arg, str) for arg in docker):
        raise SearchError("docker_command_must_be_argv")
    containers = []

    def run(*args):
        result = subprocess.run([*docker, *args], capture_output=True, text=True, timeout=90)
        if result.returncode:
            raise SearchError("docker_operation_failed")
        return result.stdout.strip()

    def start(kind, port, options):
        container = run("run", "--detach", "--label", "asr-search-test=true", "--cpus", "2",
                        "--pids-limit", "512", "--name", "asr-search-" + uuid.uuid4().hex[:12],
                        "--publish", f"127.0.0.1::{port}", *options, IMAGES[kind])
        containers.append(container)
        address = run("port", container, f"{port}/tcp")
        client = LocalHTTP("http://" + address)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                client.request("GET", "/")
                return client
            except SearchError:
                if run("inspect", "--format", "{{.State.Running}}", container) != "true":
                    raise SearchError("database_container_exited") from None
                time.sleep(0.5)
        raise SearchError("database_readiness_timeout")

    try:
        search = start("opensearch", 9200, [
            "--memory", "2g", "--env", "discovery.type=single-node",
            "--env", "DISABLE_SECURITY_PLUGIN=true", "--env", "DISABLE_INSTALL_DEMO_CONFIG=true",
            "--env", "OPENSEARCH_JAVA_OPTS=-Xms512m -Xmx512m -XX:ActiveProcessorCount=2",
        ])
        vector = start("qdrant", 6333, ["--memory", "512m", "--env", "QDRANT__TELEMETRY_DISABLED=true"])
        with tempfile.TemporaryDirectory(prefix="asr-search-live-") as directory:
            paths = sorted((ROOT / "samples").glob("*/asr/*.jsonl"))
            paths += sorted((ROOT / "examples/subagent").glob("*.jsonl"))
            paths.append(PACKAGE / "tests/fixtures/search.jsonl")
            bundle = Path(directory) / "bundle"
            manifest = export(paths, bundle, index="asr-live", chunk_size=500, overlap=50,
                              embedding_command=[sys.executable, str(PACKAGE / "tests/fixture_embedder.py")],
                              dimensions=3, embedding_model="synthetic-counts-v1")
            verify_bundle(bundle)
            for _ in range(2):
                count = load_search(search, "asr-live", mapping(), read_jsonl(bundle / "documents.jsonl"), batch_size=7)
                assert count == manifest["counts"]["documents"]
                count = load_qdrant(vector, "asr-live", 3, read_jsonl(bundle / "chunks.jsonl"), batch_size=7)
                assert count == manifest["counts"]["chunks"]
            _, total = search.request("GET", "/asr-live/_count")
            assert total["count"] == manifest["counts"]["documents"]
            queries = [
                {"match": {"text": "quokka"}},
                {"term": {"resolved_paths": "/work/search/src/parser.py"}},
                {"term": {"commits": "a" * 40}},
                {"term": {"record_type": "gap"}},
                {"term": {"copied": True}},
                {"term": {"known_missing": "approvals"}},
                {"term": {"paired_call": "com.example.search:search%3Afixture#read"}},
            ]
            for query in queries:
                _, response = search.request("POST", "/asr-live/_search", {"query": query, "size": 1})
                assert response["hits"]["total"]["value"] > 0
            _, response = search.request("POST", "/asr-live/_search", {
                "query": {"term": {"citation": "com.example.search:search%3Afixture#future"}}, "size": 1})
            stored = response["hits"]["hits"][0]["_source"]["raw_json"]
            assert "0.123456789012345678901234567890" in stored
            assert '"falseValue":false' in stored
            _, response = vector.request("POST", "/collections/asr-live/points/count", {"exact": True})
            assert response["result"]["count"] == manifest["counts"]["chunks"]
            _, response = vector.request("POST", "/collections/asr-live/points/query", {
                "query": [5, 1, 1], "limit": 3, "with_payload": True,
                "filter": {"must": [{"key": "citation", "match": {
                    "value": "com.example.search:search%3Afixture#prompt%201"}}]},
            })
            assert response["result"]["points"]
            for point in response["result"]["points"]:
                assert point["payload"]["author"] == "human"
                assert "quokka" in point["payload"]["text"]
                assert point["payload"]["citation"].endswith("#prompt%201")
            additional = {"sessions": 0, "documents": 0, "chunks": 0}
            examples = sorted(p for p in (ROOT / "examples").glob("*.jsonl")
                              if not p.name.endswith(".annotations.jsonl"))
            # Several examples are alternate snapshots with the same native identity.
            for number, path in enumerate(examples):
                name = f"asr-example-{number}"
                other = Path(directory) / name
                result = export([path], other, index=name,
                                embedding_command=[sys.executable, str(PACKAGE / "tests/fixture_embedder.py")],
                                dimensions=3, embedding_model="synthetic-counts-v1")
                assert load_search(search, name, mapping(), read_jsonl(other / "documents.jsonl")) == result["counts"]["documents"]
                assert load_qdrant(vector, name, 3, read_jsonl(other / "chunks.jsonl")) == result["counts"]["chunks"]
                _, stored = search.request("GET", "/" + name + "/_count")
                assert stored["count"] == result["counts"]["documents"]
                _, stored = vector.request("POST", "/collections/" + name + "/points/count", {"exact": True})
                assert stored["result"]["count"] == result["counts"]["chunks"]
                for key in additional:
                    additional[key] += result["counts"].get(key, 0)
            evidence = {"schema_version": 1, "images": IMAGES,
                        "image_ids": {kind: run("image", "inspect", "--format", "{{.Id}}", name)
                                      for kind, name in IMAGES.items()},
                        "counts": manifest["counts"], "additional_examples": additional,
                        "search_queries": len(queries) + 1,
                        "repeat_loads": 2, "vector_query": "passed", "raw_precision": "passed",
                        "status": "passed"}
        print(dumps(evidence))
    finally:
        for container in reversed(containers):
            run("stop", "--time", "10", container)
            run("rm", container)


if __name__ == "__main__":
    main()
