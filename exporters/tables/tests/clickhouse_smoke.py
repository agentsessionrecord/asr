"""Run only when requested. No published ports."""

import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import time

import duckdb

from asr_tables import export
from asr_tables.loaders import clickhouse_ddl, load_duckdb
from asr_tables.schema import SCHEMAS

HERE = Path(__file__).resolve().parent
IMAGE = "clickhouse/clickhouse-server:25.8@sha256:0152dd511befe6a2c2ef53e930726179669b08116da78500b37c51c96ff5ee77"
CONFIG = """<clickhouse>
  <max_thread_pool_size>512</max_thread_pool_size>
  <max_thread_pool_free_size>32</max_thread_pool_free_size>
  <thread_pool_queue_size>4096</thread_pool_queue_size>
  <background_schedule_pool_size>16</background_schedule_pool_size>
  <background_buffer_flush_schedule_pool_size>4</background_buffer_flush_schedule_pool_size>
  <background_message_broker_schedule_pool_size>4</background_message_broker_schedule_pool_size>
  <background_distributed_schedule_pool_size>4</background_distributed_schedule_pool_size>
  <tables_loader_foreground_pool_size>4</tables_loader_foreground_pool_size>
  <tables_loader_background_pool_size>4</tables_loader_background_pool_size>
  <async_load_databases>false</async_load_databases>
  <listen_host replace="replace">127.0.0.1</listen_host>
  <send_crash_reports><enabled>false</enabled></send_crash_reports>
</clickhouse>
"""


def smoke():
    docker = shlex.split(os.environ.get("ASR_TABLES_DOCKER", "docker"))
    container = None
    with tempfile.TemporaryDirectory(prefix="asr-tables-clickhouse-") as scratch:
        dataset = Path(scratch) / "tables"
        manifest = export(sorted((HERE / "fixtures").glob("*.jsonl")), dataset)
        database = Path(scratch) / "tables.duckdb"
        load_duckdb(dataset, database)
        config = Path(scratch) / "test-config.xml"
        config.write_text(CONFIG)
        config.chmod(0o644)
        try:
            result = subprocess.run(docker + ["run", "--rm", "--detach", "--network", "none",
                "--memory", "2g", "--cpus", "2", "--pids-limit", "1024",
                "--env", "CLICKHOUSE_SKIP_USER_SETUP=1",
                "--volume", f"{config}:/etc/clickhouse-server/config.d/asr-test.xml:ro", IMAGE],
                check=True, capture_output=True, text=True, timeout=60)
            container = result.stdout.strip()

            def query(sql, data=None):
                return subprocess.run(docker + ["exec", "--interactive", container,
                    "clickhouse-client", "--host", "127.0.0.1", "--max_threads", "2",
                    "--multiquery", "--format", "TSVRaw", "--query", sql],
                    input=data, capture_output=True, timeout=45)

            ready = False
            for _ in range(45):
                if query("SELECT 1").returncode == 0:
                    ready = True
                    break
                time.sleep(1)
            if not ready:
                logs = subprocess.run(docker + ["logs", "--tail", "30", container],
                                      capture_output=True, timeout=10)
                print(logs.stdout.decode(), logs.stderr.decode())
                raise RuntimeError("clickhouse-not-ready")
            version = query("SELECT version()")
            assert version.returncode == 0
            print("ClickHouse", version.stdout.decode().strip())
            ddl = query(clickhouse_ddl())
            assert ddl.returncode == 0, ddl.stderr.decode()
            for name in SCHEMAS:
                loaded = query(f"INSERT INTO `{name}` FORMAT Parquet", (dataset / (name + ".parquet")).read_bytes())
                assert loaded.returncode == 0, loaded.stderr.decode()
                count = query(f"SELECT count() FROM `{name}`")
                assert count.returncode == 0 and int(count.stdout) == manifest["tables"][name]
            with duckdb.connect(str(database)) as connection:
                queries = [
                    "SELECT sum(input_tokens), sum(output_tokens) FROM inferences WHERE original",
                    "SELECT sum(cost_amount) FROM inferences WHERE original AND cost_currency='USD'",
                    "SELECT count(*) FROM inferences WHERE original AND cost_amount_text IS NULL",
                    "SELECT count(*) FROM tool_calls WHERE pairing='ambiguous' AND outcome='unknown'",
                    "SELECT count(*) FROM links WHERE resolved=false",
                ]
                for sql in queries:
                    expected = connection.execute(sql).fetchone()
                    actual = query(sql)
                    assert actual.returncode == 0, actual.stderr.decode()
                    fields = actual.stdout.decode().strip().split("\t")
                    assert len(fields) == len(expected)
                    from decimal import Decimal
                    assert [Decimal(field) for field in fields] == [Decimal(value) for value in expected]
                for path in sorted((HERE.parent / "queries").glob("*.sql")):
                    result = query(path.read_text())
                    assert result.returncode == 0, result.stderr.decode()
            print(f"PASS: {len(SCHEMAS)} tables, row counts, 5 cross-engine checks, 5 SQL examples")
        finally:
            if container:
                subprocess.run(docker + ["rm", "--force", container],
                               check=True, capture_output=True, timeout=45)
                print("Removed test container")


if __name__ == "__main__":
    smoke()
