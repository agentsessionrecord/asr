"""Run synthetic Codex hook checks through the compatible endpoint with disposable config.

Run from the repository root with the workspace Python interpreter. Only aggregate
counts are retained. The temporary home, transcript and credential environment
are removed when the test finishes.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

from asr_codex_hooks.recorder import VENDOR

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from live_provider import loopback_endpoint
ROOT = Path(__file__).resolve().parents[3]
POLICY = '''import json, sys
p = json.load(sys.stdin)
event = p["hook_event_name"]
command = p.get("tool_input", {}).get("command", "")
if event == "PreToolUse" and "ASR_ORIGINAL" in command:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event,
        "permissionDecision": "allow", "updatedInput": {"command": "printf ASR_REWRITTEN"}}}))
elif event == "PermissionRequest" and "ASR_REFUSED" in command:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event,
        "decision": {"behavior": "deny", "message": "Synthetic hook refusal"}}}))
'''
PROMPT = """This is a synthetic hook recorder check in an empty scratch directory.
Make exactly three separate exec_command tool calls in this order. Do not combine them.
1. Run command `printf ASR_ALLOWED` with default sandbox permissions.
2. Run command `printf ASR_REFUSED` with sandbox_permissions require_escalated and
   justification `Synthetic hook approval check`. If refused, accept the refusal.
3. Run command `printf ASR_ORIGINAL` with default sandbox permissions. A test hook
   will replace the command. Accept the hook rewrite without retrying the original.
Use login false for the three calls. Do not use subagents, read any files, install
anything, contact any service or run other commands. Finish with a short reply.
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--base-url", default=os.environ.get("ASR_OPENAI_BASE_URL"))
    parser.add_argument("--model", default=os.environ.get("ASR_OPENAI_MODEL"))
    args = parser.parse_args()
    endpoint = loopback_endpoint(args.base_url)
    if not args.model:
        parser.error("--model or ASR_OPENAI_MODEL is required")
    destination = args.destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    credential = args.key_file.read_text().strip()
    with tempfile.TemporaryDirectory(prefix="asr-codex-live-") as temporary:
        scratch = Path(temporary)
        scratch.chmod(0o700)
        home, config, work = (scratch / name for name in ("home", "codex", "work"))
        for path in (home, config, work):
            path.mkdir(mode=0o700)
        output = scratch / "asr"
        generated = subprocess.run([sys.executable, "-m", "asr_codex_hooks", "config", "--full", "--output", str(output)],
                                   check=True, capture_output=True, text=True)
        hooks = json.loads(generated.stdout)
        policy = scratch / "policy.py"
        policy.write_text(POLICY)
        for name in ("PreToolUse", "PermissionRequest"):
            command = shlex.join([sys.executable, "-m", "asr_codex_hooks", "wrap", "--full", "--output", str(output),
                                  "--", sys.executable, str(policy)])
            hooks["hooks"][name].append({"hooks": [{"type": "command", "command": command, "timeout": 2}]})
        (config / "hooks.json").write_text(json.dumps(hooks))
        (config / "rules").mkdir(mode=0o700)
        (config / "rules" / "default.rules").write_text(
            'prefix_rule(pattern=["printf", "ASR_REFUSED"], decision="prompt")\n')
        settings = f'''model = {json.dumps(args.model)}
model_provider = "asr_test"
model_reasoning_effort = "low"
approval_policy = "on-request"
sandbox_mode = "workspace-write"
approvals_reviewer = "auto_review"
[features]
hooks = true
[model_providers.asr_test]
name = "Synthetic test endpoint"
base_url = {json.dumps(endpoint)}
http_headers = {{ Authorization = {json.dumps("Bearer " + credential)} }}
wire_api = "responses"
'''
        provider = config / "config.toml"
        with provider.open("x") as stream:
            os.chmod(provider, 0o600)
            stream.write(settings)
        import tomllib
        parsed = tomllib.loads(provider.read_text())
        assert parsed["model_provider"] == "asr_test"
        assert loopback_endpoint(parsed["model_providers"]["asr_test"]["base_url"]) == endpoint
        environment = {"PATH": os.environ["PATH"], "HOME": str(home), "CODEX_HOME": str(config),
                       "TMPDIR": str(scratch), "NO_COLOR": "1"}
        # Avoid exposing provider output or native session text in the report.
        with (scratch / "stdout").open("wb") as stdout, (scratch / "stderr").open("wb") as stderr:
            run = subprocess.run(["codex", "exec", "--skip-git-repo-check", "--dangerously-bypass-hook-trust",
                                  "--json", "-s", "danger-full-access", "-C", str(work), PROMPT], env=environment, cwd=work,
                                 stdout=stdout, stderr=stderr, timeout=240)
        rows = [json.loads(line) for path in output.glob("*.jsonl") for line in path.read_text().splitlines()]
        counts = Counter(r["type"] for r in rows)
        events = Counter(r.get("_meta", {}).get(VENDOR, {}).get("hook_event_name") for r in rows)
        results = [r for r in rows if r["type"] == "tool_result"]
        observations = [r.get("_meta", {}).get(VENDOR, {}) for r in rows]
        outcomes = [r["commandHookResponse"] for r in observations if "commandHookResponse" in r]
        verdicts = []
        for response in outcomes:
            try:
                value = json.loads(response.get("stdout", ""))
                verdicts.append(value.get("hookSpecificOutput", {}))
            except ValueError:
                pass
        validation = []
        for file in output.glob("*.jsonl"):
            validated = subprocess.run(["node", str(ROOT / "tools/validator/bin/asr-validate.js"), "--json", str(file)],
                                       check=True, capture_output=True, text=True)
            validation.append(json.loads(validated.stdout))
        diagnostics = Counter(d["code"] for report in validation for d in report.get("diagnostics", []))
        response_shapes = Counter(type(r.get("_meta", {}).get(VENDOR, {}).get("toolResponse")).__name__
                                  for r in results if "toolResponse" in r.get("_meta", {}).get(VENDOR, {}))
        response_keys = Counter(k for r in results for k in r.get("_meta", {}).get(VENDOR, {}).get("toolResponse", {})
                                if isinstance(r.get("_meta", {}).get(VENDOR, {}).get("toolResponse"), dict))
        result_text = "\n".join(p.get("text", "") for r in results for p in r.get("content", []))
        response_flags = {name: result_text.lower().count(name.lower()) for name in
                          ("bwrap", "sandbox", "permission", "not permitted", "No such file", "ASR_ALLOWED", "ASR_REWRITTEN")}
        checks = {
            "codex_exit_zero": run.returncode == 0,
            "allowed_output": any("ASR_ALLOWED" in p.get("text", "") for r in results for p in r.get("content", [])),
            "permission_request": events["PermissionRequest"] > 0,
            "denial_response_observed": any(v.get("decision", {}).get("behavior") == "deny" for v in verdicts),
            "refused_command_not_executed": not any("ASR_REFUSED" in p.get("text", "") for r in results for p in r.get("content", [])),
            "rewrite_response_observed": any("updatedInput" in v for v in verdicts),
            "effective_rewrite_input": any(r.get("input", {}).get("command") == "printf ASR_REWRITTEN" for r in results),
            "rewritten_output": any("ASR_REWRITTEN" in p.get("text", "") for r in results for p in r.get("content", [])),
            "no_invented_approval": counts["approval"] == 0,
            "session_end": events["SessionEnd"] > 0,
            "validation_zero_errors": bool(validation) and all(v["errors"] == 0 for v in validation),
        }
        summary = {"agentVersion": "0.163.0", "checks": checks, "streams": len(validation),
                   "records": sum(counts.values()), "recordTypes": dict(counts),
                   "hookEvents": {k: v for k, v in events.items() if k},
                   "validationErrors": sum(v["errors"] for v in validation), "diagnosticCodes": dict(diagnostics),
                   "responseShapes": dict(response_shapes), "responseKeys": dict(response_keys), "responseFlags": response_flags}
        destination.write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2))
        if not all(checks.values()):
            # Codes alone aid debugging without disclosing model output or paths.
            print("Live assertions failed: " + ", ".join(k for k, v in checks.items() if not v), file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
