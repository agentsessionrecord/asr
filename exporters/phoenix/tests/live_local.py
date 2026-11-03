"""Explicit synthetic import and readback against a disposable Phoenix process."""

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
from tempfile import TemporaryDirectory
from threading import Event
from time import monotonic
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener

from asr_evals.dataset import rows
from asr_evals.reader import read_session
from asr_phoenix import export
from asr_phoenix.local import load


def port():
    with socket.socket() as channel:
        channel.bind(("127.0.0.1", 0))
        return channel.getsockname()[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--service-python", required=True)
    parser.add_argument("--log-file", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    session = read_session(root / "exporters/evals/tests/fixtures/session.jsonl")
    options = SimpleNamespace(include_content=True, inference_ts="end", tool_times=True, dataset_name="synthetic-asr-evals")
    artifacts = export([session], rows([session], include_content=True), options)
    http_port, grpc_port = port(), port()
    endpoint = f"http://127.0.0.1:{http_port}"
    opener = build_opener(ProxyHandler({}))
    pause = Event()
    with TemporaryDirectory(prefix="asr-phoenix-live-") as scratch:
        directory = Path(scratch)
        for name, data in artifacts.items():
            (directory / name).write_bytes(data if isinstance(data, bytes) else data.encode())
        environment = {"PATH": os.defpath, "PHOENIX_WORKING_DIR": str(directory / "runtime"),
                       "PHOENIX_HOST": "127.0.0.1", "PHOENIX_PORT": str(http_port),
                       "PHOENIX_GRPC_PORT": str(grpc_port), "PHOENIX_ALLOW_EXTERNAL_RESOURCES": "false",
                       "PHOENIX_LOGGING_LEVEL": "WARNING", "PHOENIX_DB_LOGGING_LEVEL": "ERROR",
                       "PHOENIX_LOG_MIGRATIONS": "false"}
        log_fd = os.open(args.log_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(log_fd, "wb") as log:
            process = subprocess.Popen([args.service_python, "-m", "phoenix.server.main", "--host", "127.0.0.1",
                                        "--port", str(http_port), "--no-internet", "--no-ui", "serve"],
                                       env=environment, stdout=log, stderr=log)
            try:
                deadline = monotonic() + 40
                while True:
                    if process.poll() is not None:
                        raise RuntimeError("service_exited")
                    try:
                        with opener.open(endpoint + "/readyz", timeout=1) as response:
                            if response.status == 200:
                                break
                    except (URLError, TimeoutError):
                        pass
                    if monotonic() > deadline:
                        raise RuntimeError("service_readiness_timeout")
                    pause.wait(0.1)
                statuses = load(endpoint, directory)
                assert statuses == [200, 200]
                # Ingestion is asynchronous. Bound readback by a real deadline.
                deadline = monotonic() + 20
                while True:
                    try:
                        with opener.open(endpoint + "/v1/projects/synthetic-asr-evals/spans?limit=100", timeout=3) as response:
                            spans = json.load(response)["data"]
                    except HTTPError as error:
                        if error.code != 404:
                            raise
                        spans = []
                    if len(spans) == 5:
                        break
                    if monotonic() > deadline:
                        raise RuntimeError("span_readback_timeout")
                    pause.wait(0.1)
                with opener.open(endpoint + "/v1/datasets", timeout=3) as response:
                    datasets = json.load(response)["data"]
                dataset = next(d for d in datasets if d["name"] == options.dataset_name)
                with opener.open(endpoint + "/v1/datasets/" + dataset["id"] + "/examples", timeout=3) as response:
                    examples = json.load(response)["data"]["examples"]
                assert len(examples) == 1
                assert examples[0]["input"]["starting_commit"] == "a" * 40
                assert examples[0]["output"]["final_diff"]
                assert examples[0]["input"]["task_prompt"] == rows([session], include_content=True)[0]["input"]["task_prompt"]
                print(f"phoenix_live=passed statuses={','.join(map(str, statuses))} spans={len(spans)} datasets=1 examples={len(examples)}")
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
