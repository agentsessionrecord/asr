"""Run real scratch agents, then follow their converted bytes through ASR tools."""

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

from providers import PROVIDER, CheckFailure, private_file, require, verify
from s3 import LocalS3

ROOT = Path("/opt/asr")
AGENTS = ("claude-code", "codex", "pi")
CORE_TYPES = {"session", "session_info", "message", "tool_call", "tool_result", "approval",
              "file_change", "vcs", "inference", "gap"}
STATUS = {"stage": "provider_checks"}
SYSTEM = ("Follow this synthetic test exactly. Use only the requested tool and command. "
          "Do not read files, credentials, settings or environment variables. Do not access "
          "the network, start agents, install software or run other commands.")


def run(argv, *, env=None, cwd=None, timeout=120):
    with subprocess.Popen([str(arg) for arg in argv], env=env, cwd=cwd,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          start_new_session=True) as process:
        try:
            stdout, _ = process.communicate(timeout=timeout)
            require(process.returncode == 0, "process_failed_" + Path(argv[0]).name.replace("-", "_"))
            return stdout
        finally:
            # Stop only this process group, including children left by a timeout.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def rows(path):
    return [json.loads(line) for line in path.read_bytes().splitlines()]


def recorded_text(record):
    parts = [part["text"] for part in record.get("content", [])
             if part.get("type") == "text" and isinstance(part.get("text"), str)]
    parts.extend(value for name, value in record.get("exec", {}).items()
                 if name in ("stdout", "output") and isinstance(value, str))
    return "\n".join(parts)


def agent_environment(directory):
    environment = {"PATH": os.environ["PATH"], "LANG": "C.UTF-8", "NO_COLOR": "1"}
    for name, folder in (("HOME", "home"), ("XDG_CONFIG_HOME", "config"),
                         ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state"),
                         ("TMPDIR", "tmp")):
        path = directory / folder
        path.mkdir(mode=0o700)
        environment[name] = str(path)
    return environment


def live_agents(scratch, providers, credential):
    sources, captures, sessions = {}, {}, {}
    for agent in AGENTS:
        STATUS["stage"] = "agent_" + agent.replace("-", "_")
        directory = scratch / agent
        directory.mkdir(mode=0o700)
        work = directory / "work"
        work.mkdir(mode=0o700)
        env = agent_environment(directory)
        capture = directory / "captures"
        capture.mkdir(mode=0o700)
        marker = "ASR_E2E_" + agent.upper().replace("-", "_")
        prompt = (f"Use {'exec_command' if agent == 'codex' else 'Bash' if agent == 'claude-code' else 'bash'} "
                  f"once to run exactly `printf {marker}`. Do not combine commands. "
                  f"Then reply with exactly {marker}_DONE.")
        if agent == "claude-code":
            config = directory / "claude"
            config.mkdir(mode=0o700)
            env.update(CLAUDE_CONFIG_DIR=str(config), DISABLE_AUTOUPDATER="1",
                       CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1")
            prefix = directory / "plugin"
            run(["python3", "-I", "-S", ROOT / "plugins/hooks-core/install.py", agent,
                 "--prefix", prefix, "--output-dir", capture, "--content", "full"], env=env)
            settings = directory / "provider.json"
            private_file(settings, (providers / "claude.json").read_text())
            require(json.loads(settings.read_text())["env"]["ANTHROPIC_BASE_URL"] == json.loads((providers / "claude.json").read_text())["env"]["ANTHROPIC_BASE_URL"],
                    "claude_runtime_endpoint_not_local")
            run(["claude", "plugin", "validate", prefix / "claude-code", "--strict", "--json"],
                env=env, cwd=work)
            command = ["claude", "-p", "--model", json.loads(settings.read_text())["model"], "--effort", "low", "--max-budget-usd", "0.5",
                       "--setting-sources", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                       "--no-chrome", "--prompt-suggestions", "false", "--settings", settings,
                       "--plugin-dir", prefix / "claude-code", "--output-format", "stream-json", "--verbose",
                       "--system-prompt", SYSTEM, "--permission-mode", "manual", "--permission-prompts", "none",
                       "--tools", "Bash", "--allowedTools", "Bash(printf *)", "--", prompt]
            sources[agent] = config / "projects"
        elif agent == "codex":
            config = directory / "codex"
            config.mkdir(mode=0o700)
            env["CODEX_HOME"] = str(config)
            settings = config / "config.toml"
            private_file(settings, (providers / "codex.toml").read_text())
            import tomllib
            parsed = tomllib.loads(settings.read_text())
            require(parsed["model_provider"] == PROVIDER and
                    parsed["model_providers"][PROVIDER]["base_url"] == json.loads((providers / "pi.json").read_text())["providers"][PROVIDER]["baseUrl"],
                    "codex_runtime_endpoint_not_local")
            hooks = run(["asr-codex-hook", "config", "--full", "--output", capture], env=env)
            private_file(config / "hooks.json", hooks.decode())
            command = ["codex", "exec", "--skip-git-repo-check", "--dangerously-bypass-hook-trust",
                       "--json", "-C", work, SYSTEM + "\n" + prompt]
            sources[agent] = config / "sessions"
        else:
            config = directory / "pi"
            config.mkdir(mode=0o700)
            env.update(PI_CODING_AGENT_DIR=str(config), PI_OFFLINE="1", PI_TELEMETRY="0",
                       ASR_OUTPUT_DIR=str(capture), ASR_CONTENT="full")
            settings = config / "models.json"
            private_file(settings, (providers / "pi.json").read_text())
            require(json.loads(settings.read_text())["providers"][PROVIDER]["baseUrl"] == json.loads((providers / "pi.json").read_text())["providers"][PROVIDER]["baseUrl"],
                    "pi_runtime_endpoint_not_local")
            sources[agent] = directory / "sessions"
            command = ["pi", "--print", "--mode", "json", "--offline", "--no-approve",
                       "--no-extensions", "--no-mcp", "--no-skills", "--no-context-files",
                       "--no-prompt-templates", "--no-themes", "--extension", "/opt/asr-pi/index.mjs",
                       "--provider", PROVIDER, "--model", json.loads(settings.read_text())["providers"][PROVIDER]["models"][0]["id"], "--thinking", "low",
                       "--session-dir", sources[agent], "--tools", "bash", "--system-prompt", SYSTEM, "--", prompt]
        # Recheck all provider files immediately before each model process starts.
        require(verify(providers) == credential, "provider_settings_changed")
        result = run(command, env=env, cwd=work, timeout=240)
        require(credential.encode() not in result, "credential_in_agent_stdout")
        settings.unlink()
        files = sorted(capture.rglob("*.jsonl"))
        require(len(files) == 1, "plugin_stream_count_" + agent.replace("-", "_"))
        recorded = rows(files[0])
        require(recorded[0]["agent"]["name"] == agent, "plugin_agent_identity")
        calls = [row for row in recorded if row["type"] == "tool_call"]
        results = [row for row in recorded if row["type"] == "tool_result"]
        require(len(calls) == len(results) == 1 and calls[0]["callId"] == results[0].get("callId"),
                "plugin_tool_pair_" + agent.replace("-", "_"))
        require(marker in recorded_text(results[0]), "plugin_tool_output_missing")
        if agent != "codex":
            require(any(row.get("role") == "assistant" and marker + "_DONE" in recorded_text(row)
                        for row in recorded), "plugin_assistant_missing_" + agent.replace("-", "_"))
        else:
            require("assistant_messages" in recorded[0].get("missing", []), "codex_assistant_loss_undeclared")
        require(any(sources[agent].rglob("*.jsonl")), "native_session_missing")
        sessions[agent] = recorded[0]["sessionId"]
        captures[agent] = files[0]
    # Agent output must not retain a proxy credential outside provider settings.
    for path in scratch.rglob("*"):
        if path.is_file():
            require(credential.encode() not in path.read_bytes(), "credential_in_session_artifacts")
    return sources, captures, sessions


def validate(paths):
    reports = []
    for path in paths:
        report = json.loads(run(["node", ROOT / "tools/validator/bin/asr-validate.js", "--json", path]))
        require(report["errors"] == 0, "validator_errors")
        reports.append(report)
    return {"files": len(reports), "errors": sum(report["errors"] for report in reports),
            "warnings": sum(report["warnings"] for report in reports),
            "codes": dict(Counter(diagnostic["code"] for report in reports
                                  for diagnostic in report.get("diagnostics", [])))}


def collect(scratch, sources, sessions):
    client = LocalS3(os.environ["AWS_ENDPOINT"], os.environ["AWS_ACCESS_KEY_ID"], os.environ["AWS_SECRET_ACCESS_KEY"])
    bucket = "asr-e2e-synthetic"
    client.request("PUT", "/" + bucket)
    command = ["asr", "collect", "--target", "s3://" + bucket + "/run", "--state", scratch / "collector",
               "--machine", "synthetic-machine", "--uploader", "synthetic-uploader", "--window-seconds", "1"]
    expected = {}
    for agent, source in sources.items():
        command.extend(["--source", f"{agent}={source}"])
        output = scratch / ("converted-" + agent)
        run(["asr", "convert", "--agent", agent, source, "--out", output])
        converted = list(output.glob("*.jsonl"))
        require(len(converted) == 1, "converted_session_count")
        stream = converted[0].read_bytes()
        header = json.loads(stream.splitlines()[0])
        require(header["sessionId"] == sessions[agent] and header["agent"]["name"] == agent,
                "native_plugin_identity_mismatch")
        require(header["producer"]["method"] == "converter", "converter_producer_missing")
        marker = "ASR_E2E_" + agent.upper().replace("-", "_") + "_DONE"
        require(any(row.get("role") == "assistant" and marker in recorded_text(row)
                    for row in rows(converted[0])), "converted_assistant_missing")
        require(any(row["type"] == "tool_result" and marker.removesuffix("_DONE") in recorded_text(row)
                    for row in rows(converted[0])), "converted_tool_output_missing")
        expected[hashlib.sha256(stream).hexdigest()] = stream
    first = json.loads(run(command))
    require(first["uploaded_sessions"] == 3, "collect_upload_count")
    # Close the one-second receipt window, then prove an unchanged restart is a no-op.
    time.sleep(1.1)
    second = json.loads(run(command))
    require(second["converted_sessions"] == second["uploaded_sessions"] == 0, "collect_restart_not_idempotent")
    downloads = scratch / "downloaded"
    downloads.mkdir(mode=0o700)
    objects, manifests = [], []
    for key in client.keys(bucket):
        body, headers = client.request("GET", "/" + bucket + "/" + key)
        digest = hashlib.sha256(body).hexdigest()
        require(headers.get("x-amz-meta-sha256") == digest, "s3_metadata_digest_mismatch")
        if key.endswith(".jsonl"):
            require(key == "run/objects/" + digest + ".jsonl", "s3_object_key_mismatch")
            require(expected.get(digest) == body, "s3_exact_bytes_mismatch")
            file = downloads / (digest + ".jsonl")
            private_file(file, body.decode())
            objects.append(file)
        else:
            require(key.endswith(".manifest.json"), "unexpected_s3_object")
            file = downloads / key.rsplit("/", 1)[1]
            private_file(file, body.decode())
            manifests.append(file)
    require(len(objects) == len(expected) == 3 and bool(manifests), "s3_download_count")
    receipts = [entry for file in manifests for entry in json.loads(file.read_text())["entries"]]
    require(len(receipts) == 3 and {entry["sha256"] for entry in receipts} == set(expected), "receipt_digest_coverage")
    for entry in receipts:
        require(entry["status"] == "received" and entry["byteLength"] == len(expected[entry["sha256"]]),
                "receipt_bytes_or_status_mismatch")
    return objects, manifests, {"objects": len(objects), "manifests": len(manifests),
                                "receipts": len(receipts), "exactBytes": True, "unchangedRestart": True}


def exports(scratch, files):
    original = {file: file.read_bytes() for file in files}
    otel, tables, search = (scratch / name for name in ("otel", "tables", "search"))
    run(["asr-otel", *files, "--include-content", "--include-identity", "--output", otel])
    run(["asr-tables", "export", *files, "--output", tables])
    run(["asr-tables", "duckdb", tables, scratch / "sessions.duckdb"])
    run(["asr-search", "export", *files, "--output", search])
    expected = {(stream[0]["agent"]["name"] + ":" + stream[0]["sessionId"], row["id"]): row
                for file in files for stream in [rows(file)] for row in stream}
    telemetry = json.loads((otel / "logs.json").read_text())
    logs = [row for resource in telemetry["resourceLogs"] for scope in resource["scopeLogs"]
            for row in scope["logRecords"]]
    telemetry_expected = {identity for identity, row in expected.items() if row["type"] in CORE_TYPES}
    def attribute(row, name):
        return next(item["value"]["stringValue"] for item in row["attributes"] if item["key"] == name)
    require(len(logs) == len(telemetry_expected) and
            {(attribute(row, "asr.session_ref"), attribute(row, "asr.record_id")) for row in logs} == telemetry_expected,
            "otel_record_coverage")
    require(all(json.loads(attribute(row, "asr.record.json")) == expected[
        (attribute(row, "asr.session_ref"), attribute(row, "asr.record_id"))] for row in logs), "otel_raw_content")
    import pyarrow.parquet as parquet
    table_records = parquet.read_table(tables / "records.parquet").to_pylist()
    require(len(table_records) == len(expected) and
            {(row["session_ref"], row["record_id"]) for row in table_records} == set(expected), "tables_record_coverage")
    require(all(json.loads(row["raw_json"]) == expected[(row["session_ref"], row["record_id"])]
                for row in table_records), "tables_raw_content")
    import duckdb
    with duckdb.connect(str(scratch / "sessions.duckdb"), read_only=True) as database:
        require(database.execute("SELECT count(*) FROM records").fetchone()[0] == len(expected),
                "duckdb_record_coverage")
    documents = rows(search / "documents.jsonl")
    require(len(documents) == len(expected) and
            {(row["session_ref"], row["record_id"]) for row in documents} == set(expected), "search_record_coverage")
    require(all(json.loads(row["raw_json"]) == expected[(row["session_ref"], row["record_id"])]
                for row in documents), "search_raw_content")
    from asr_search.bundle import verify_bundle
    manifest = verify_bundle(search)
    require(manifest["counts"]["sessions"] == 3 and manifest["counts"]["chunks"] > 0, "search_bundle_empty")
    for file, content in original.items():
        require(file.read_bytes() == content, "export_modified_input")
    report = json.loads((otel / "report.json").read_text())
    omitted = len(expected) - len(telemetry_expected)
    diagnostic_codes = Counter(item["code"] for item in report["diagnostics"])
    require(diagnostic_codes["unknown_record_type"] == omitted, "otel_unknown_record_diagnostics")
    return {"otelLogs": len(logs), "otelSpans": report["spans"],
            "otelDiagnosticCodes": dict(diagnostic_codes), "otelUnknownRecordsSkipped": omitted,
            "tableRecords": len(table_records), "searchDocuments": len(documents),
            "searchChunks": manifest["counts"]["chunks"], "recordCoverage": True, "rawContent": True}


def main():
    os.umask(0o077)
    providers = Path("/run/asr-providers")
    credential = verify(providers)
    with tempfile.TemporaryDirectory(prefix="asr-e2e-sessions-") as temporary:
        scratch = Path(temporary)
        sources, captures, sessions = live_agents(scratch, providers, credential)
        STATUS["stage"] = "plugin_validation"
        plugin_validation = validate(captures.values())
        STATUS["stage"] = "collection"
        files, manifests, collection = collect(scratch, sources, sessions)
        STATUS["stage"] = "collection_validation"
        collection_validation = validate([*files, *manifests])
        STATUS["stage"] = "viewer"
        browser = json.loads(run(["node", ROOT / "tests/e2e/viewer.mjs", *files]))
        STATUS["stage"] = "exports"
        export_results = exports(scratch, files)
        print(json.dumps({"passed": True, "agents": list(AGENTS), "plugins": len(captures),
                          "pluginValidation": plugin_validation, "collectionValidation": collection_validation,
                          "collection": collection, "viewer": browser, "exports": export_results}, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (CheckFailure, subprocess.TimeoutExpired, OSError, ValueError, KeyError, StopIteration) as error:
        print(json.dumps({"passed": False, "code": str(error) if isinstance(error, CheckFailure)
                          else type(error).__name__, "stage": STATUS["stage"]}), flush=True)
        raise SystemExit(1)
