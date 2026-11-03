"""Isolated compatible endpoint smoke test. Print counts only and remove all captures."""
from __future__ import annotations

from collections import Counter
import argparse
import json
from multiprocessing import Pipe, Process
import os
from pathlib import Path
import subprocess
import tempfile
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

from agent_session_record import Writer
from asr_telemetry_approvals import import_approvals
from asr_telemetry_approvals.telemetry import documents, events

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from live_provider import loopback_endpoint, private_json
ROOT = Path(__file__).resolve().parents[3]


def collector(path, pipe):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            data = self.rfile.read(int(self.headers["Content-Length"]))
            with open(path, "ab") as stream:
                stream.write(data + b"\n")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    pipe.send(server.server_port)
    server.serve_forever()


def convert_sample(native, target, agent, version):
    """Sample-pattern conversion of tool evidence only, not a rollout converter."""
    rows = [json.loads(line) for line in native.read_text().splitlines()]
    session = next((r.get("sessionId") for r in rows if r.get("sessionId")), None) if agent == "claude-code" else next(r["payload"]["id"] for r in rows if r.get("type") == "session_meta")
    calls, results = {}, {}
    for position, row in enumerate(rows):
        if agent == "claude-code":
            for block in row.get("message", {}).get("content", []) if isinstance(row.get("message", {}).get("content"), list) else []:
                if block.get("type") == "tool_use":
                    calls[block["id"]] = (position, {"callId": block["id"], "name": block["name"], "input": block["input"]})
                if block.get("type") == "tool_result":
                    result = {"callId": block["tool_use_id"]}
                    result["status"] = "failed" if block.get("is_error") is True else "completed" if block.get("is_error") is False else "unknown"
                    results[block["tool_use_id"]] = (position, result)
        else:
            p = row.get("payload", {})
            if row.get("type") == "response_item" and p.get("type") in ("function_call", "custom_tool_call", "local_shell_call"):
                calls[p["call_id"]] = (position, {"callId": p["call_id"], "name": p.get("name", p["type"])})
            if row.get("type") == "response_item" and p.get("type") in ("function_call_output", "custom_tool_call_output"):
                results[p["call_id"]] = (position, {"callId": p["call_id"], "status": "unknown"})
            # New code-mode items expose the invoked shell as structured data.
            item = p.get("item", {}) if p.get("type") == "item_completed" else p
            if item.get("type") in ("CommandExecution", "command_execution"):
                identity = item.get("id", item.get("call_id"))
                if identity:
                    calls[identity] = (position, {"callId": identity, "name": "CommandExecution"})
                    results[identity] = (position, {"callId": identity, "status": item.get("status") if item.get("status") in ("completed", "failed") else "unknown"})
    with Writer(target, {"agent": {"name": agent, "version": version}, "sessionId": session,
                        "producer": {"name": "telemetry-live-sample", "version": "0.1", "method": "converter", "source": "scratch-tool-evidence"},
                        "missing": ["approvals", "messages", "tool_output", "usage", "model", "timestamps", "agent_settings", "file_changes", "commits", "copies", "tools", "exit_codes"]}) as writer:
        ordered = []
        for index, (call, (position, record)) in enumerate(calls.items()):
            ordered.append((position, 0, {"type": "tool_call", "id": f"call-{index}", **record}))
            if call in results:
                result_position, result = results[call]
                ordered.append((result_position, 1, {"type": "tool_result", "id": f"result-{index}", **result}))
        for _, _, record in sorted(ordered, key=lambda item: item[:2]):
            writer.append(record)
    return len(calls)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--agent', choices=['claude-code', 'codex'])
    parser.add_argument('--key-file', type=Path, required=True)
    parser.add_argument('--openai-base-url', default=os.environ.get('ASR_OPENAI_BASE_URL'))
    parser.add_argument('--anthropic-base-url', default=os.environ.get('ASR_ANTHROPIC_BASE_URL'))
    parser.add_argument('--openai-model', default=os.environ.get('ASR_OPENAI_MODEL'))
    parser.add_argument('--anthropic-model', default=os.environ.get('ASR_ANTHROPIC_MODEL'))
    args = parser.parse_args()
    for agent, protocol in (('codex', 'openai'), ('claude-code', 'anthropic')):
        if args.agent and args.agent != agent:
            continue
        loopback_endpoint(getattr(args, protocol + '_base_url'))
        if not getattr(args, protocol + '_model'):
            parser.error(protocol + ' model is required')
    cache = Path.home() / ".cache"
    cache.mkdir(exist_ok=True)
    key = args.key_file.read_text().strip()
    summary = {}
    with tempfile.TemporaryDirectory(prefix="asr-telemetry-live-", dir=cache) as name:
        scratch = Path(name)
        os.chmod(scratch, 0o700)
        for agent, version in (("claude-code", "2.1.305"), ("codex", "0.163.0")):
            if args.agent and args.agent != agent:
                continue
            work = scratch / agent
            work.mkdir()
            home = work / "home"
            home.mkdir()
            project = work / "project"
            project.mkdir()
            subprocess.run(["git", "init", "-q", str(project)], check=True)
            capture = work / "otel.jsonl"
            reader, sender = Pipe(duplex=False)
            process = Process(target=collector, args=(capture, sender))
            process.start()
            port = reader.recv()
            environment = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "ANTHROPIC", "CODEX", "OPENAI", "OTEL", "ASR_"))}
            environment.update({"HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"), "XDG_CACHE_HOME": str(home / ".cache")})
            prompt = "This is a scratch telemetry test. Run exactly two shell commands, separately: first printf 'ASR_DENIAL_PROBE\\n', then echo ASR_ALLOWED_PROBE. The first will be refused by a test rule. Accept that refusal and continue to the second command. Do not retry the refused command. Do not read files, use agents, delegate, use the network, or do other work. Then reply done."
            if agent == "claude-code":
                environment.update({"CLAUDE_CONFIG_DIR": str(home / ".claude"),
                                    "CLAUDE_CODE_ENABLE_TELEMETRY": "1", "OTEL_LOGS_EXPORTER": "otlp", "OTEL_METRICS_EXPORTER": "none",
                                    "OTEL_EXPORTER_OTLP_LOGS_PROTOCOL": "http/json", "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": f"http://127.0.0.1:{port}/v1/logs",
                                    "OTEL_LOGS_EXPORT_INTERVAL": "100", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"})
                settings = home / "claude-provider.json"
                private_json(settings, {"env": {"ANTHROPIC_BASE_URL": loopback_endpoint(args.anthropic_base_url), "ANTHROPIC_AUTH_TOKEN": key}})
                command = ["claude", "--settings", str(settings), "-p", prompt, "--model", args.anthropic_model, "--effort", "low", "--permission-mode", "dontAsk",
                           "--allowedTools", "Bash(echo *)", "--disallowedTools", "Bash(printf *)", "--tools", "Bash", "--strict-mcp-config",
                           "--setting-sources", "", "--safe-mode", "--output-format", "stream-json", "--verbose", "--max-budget-usd", "0.5"]
            else:
                config = home / ".codex"
                config.mkdir()
                (config / "rules").mkdir()
                (config / "rules/default.rules").write_text('prefix_rule(pattern=["printf"], decision="forbidden")\n')
                (config / "config.toml").write_text(f'''model = {json.dumps(args.openai_model)}
model_provider = "asr_test"
model_reasoning_effort = "low"
approval_policy = "never"
sandbox_mode = "danger-full-access"
[features]
multi_agent = false
[model_providers.asr_test]
name = "asr_test"
base_url = {json.dumps(loopback_endpoint(args.openai_base_url))}
http_headers = {{ Authorization = {json.dumps("Bearer " + key)} }}
wire_api = "responses"
supports_websockets = false
[otel]
exporter = {{ otlp-http = {{ endpoint = "http://127.0.0.1:{port}/v1/logs", protocol = "json" }} }}
metrics_exporter = "none"
trace_exporter = "none"
log_user_prompt = false
[analytics]
enabled = false
''')
                os.chmod(config / "config.toml", 0o600)
                import tomllib
                parsed = tomllib.loads((config / "config.toml").read_text())
                assert parsed["model_provider"] == "asr_test"
                assert loopback_endpoint(parsed["model_providers"]["asr_test"]["base_url"]) == args.openai_base_url.rstrip("/")
                environment.update({"CODEX_HOME": str(config)})
                command = ["codex", "exec", "--json", "--skip-git-repo-check", prompt]
            try:
                run = subprocess.run(command, cwd=project, env=environment, capture_output=True, timeout=150)
                if key.encode() in run.stdout or key.encode() in run.stderr:
                    raise RuntimeError("credential detected in agent output")
                if not capture.exists():
                    raise RuntimeError(f"{agent}: no telemetry capture (exit {run.returncode})")
                # The agent process flushes its exporter before returning.
                process.terminate()
                process.join(timeout=5)
                captured = capture.read_bytes()
                if key.encode() in captured:
                    raise RuntimeError("credential detected in telemetry")
                evidence = [e for doc in documents(captured.decode()) for e in events(doc)]
                decision_events = [e for e in evidence if e.name.endswith("tool_decision")]
                native_root = home / (".claude/projects" if agent == "claude-code" else ".codex/sessions")
                native = next(native_root.rglob("*.jsonl"))
                source, output = work / "input.jsonl", work / "output.jsonl"
                count = convert_sample(native, source, agent, version)
                result = import_approvals(source, [capture], output)
                validations = []
                for path in (source, output):
                    validation = subprocess.run(["node", str(ROOT / "tools/validator/bin/asr-validate.js"), str(path), "--json"], capture_output=True)
                    report = json.loads(validation.stdout)
                    validations.append({"exit": validation.returncode, "errors": report.get("errors"), "warnings": report.get("warnings")})
                approvals = [json.loads(line) for line in output.read_text().splitlines() if json.loads(line)["type"] == "approval"]
                summary[agent] = {"version": version, "exit": run.returncode, "calls": count,
                                  "telemetryDecisions": len(decision_events), "nativeDecisions": dict(Counter(e.attrs.get("decision") for e in decision_events)),
                                  "import": result, "decisions": dict(Counter(r["decision"] for r in approvals)), "validation": validations,
                                  "safetyEvents": sum(e.name.endswith("safety_event") for e in evidence)}
                if run.returncode or result["inserted"] < 1 or any(v["exit"] or v["errors"] for v in validations):
                    raise RuntimeError(f"{agent}: live import or validation failed")
                if agent == "claude-code" and (len(approvals) != 2 or not result["complete"]):
                    raise RuntimeError("Claude live coverage did not include both calls")
                if agent == "codex" and (count < 3 or result["complete"]):
                    raise RuntimeError("Codex live coverage did not retain its known telemetry loss")
            finally:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
