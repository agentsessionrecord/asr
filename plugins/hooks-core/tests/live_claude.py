#!/usr/bin/env python3
"""Optional isolated Claude integration test. Print counts and checks only."""

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from urllib.parse import urlsplit

CORE = Path(__file__).resolve().parents[1]
ROOT = CORE.parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--asr", type=Path, required=True)
    args = parser.parse_args()
    endpoint = urlsplit(args.base_url)
    if (endpoint.scheme != "http" or endpoint.hostname != "127.0.0.1" or not endpoint.port
            or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment or endpoint.path not in {"", "/"}):
        raise ValueError("An explicit loopback Anthropic endpoint is required")
    binary = str(args.asr.resolve(strict=True))
    credential = args.key_file.read_text().strip()
    if not credential:
        raise ValueError("empty proxy credential")
    executable = shutil.which("claude")
    if not executable:
        raise ValueError("Claude CLI is not installed")
    report = {"agent": "claude-code", "configuredModel": True,
              "executableSha256": hashlib.sha256(Path(executable).read_bytes()).hexdigest()}
    sources = sorted([*CORE.glob("*.py"), ROOT / "plugins/claude-code/record.py", ROOT / "plugins/claude-code/adapter.json",
                      *(ROOT / "python/agent_session_record/src/agent_session_record").glob("*.py"),
                      ROOT / "python/agent_session_record/src/agent_session_record/hook-conventions.json"])
    source_hash = hashlib.sha256()
    for source in sources:
        source_hash.update(source.relative_to(ROOT).as_posix().encode() + b"\0" + source.read_bytes() + b"\0")
    report["producerSourceSha256"] = source_hash.hexdigest()
    with tempfile.TemporaryDirectory(prefix="asr-claude-live-") as temp:
        scratch = Path(temp)
        dirs = {key: scratch / key for key in ("home", "config", "data", "state", "runtime", "claude", "workspace")}
        for directory in dirs.values():
            directory.mkdir(mode=0o700)
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(dirs["home"]),
               "XDG_CONFIG_HOME": str(dirs["config"]), "XDG_DATA_HOME": str(dirs["data"]),
               "XDG_STATE_HOME": str(dirs["state"]), "XDG_RUNTIME_DIR": str(dirs["runtime"]),
               "CLAUDE_CONFIG_DIR": str(dirs["claude"]), "DISABLE_AUTOUPDATER": "1",
               "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}
        prefix = scratch / "install"
        captures = scratch / "captures"
        subprocess.run([sys.executable, "-I", "-S", str(CORE / "install.py"), "claude-code",
                        "--prefix", str(prefix), "--output-dir", str(captures), "--content", "full"],
                       check=True, capture_output=True, env=env)
        hook = scratch / "rewrite.py"
        hook.write_text('''import json,sys
p=json.load(sys.stdin)
if p.get("tool_input",{}).get("command")=="printf asr-requested":
 print(json.dumps({"hookSpecificOutput":{"hookEventName":"PreToolUse","updatedInput":{"command":"printf asr-effective"}}}))
''')
        settings = scratch / "settings.json"
        provider = scratch / "provider-settings.json"
        with open(provider, "x", opener=lambda path, flags: os.open(path, flags, 0o600)) as file:
            json.dump({"env": {"ANTHROPIC_BASE_URL": args.base_url, "ANTHROPIC_AUTH_TOKEN": credential}}, file)
        configured = json.loads(provider.read_text())["env"]
        if configured["ANTHROPIC_BASE_URL"] != args.base_url or provider.stat().st_mode & 0o077:
            raise AssertionError("unsafe provider settings")
        report["providerSettingsVerified"] = True
        def git(*arguments):
            return subprocess.check_output(["git", "-C", str(dirs["workspace"]), *arguments], env=env, stderr=subprocess.DEVNULL, text=True).strip()
        git("init", "-q", "-b", "synthetic")
        target = dirs["workspace"] / "result.txt"
        target.write_text("before\n")
        git("add", "result.txt")
        git("-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid", "commit", "-q", "-m", "Synthetic baseline")
        head_before = git("rev-parse", "HEAD")
        settings.write_text(json.dumps({"autoMemoryEnabled": False, "hooks": {"PreToolUse": [{"hooks": [{
            "type": "command", "command": sys.executable, "args": ["-I", "-S", str(hook)],
            "timeout": 1, "onFailure": "continue"}]}]}}))
        hook_settings = json.loads(settings.read_text())
        hook_settings.update(json.loads(provider.read_text()))
        with provider.open("w") as file:
            json.dump(hook_settings, file)
        settings.unlink()
        validation = subprocess.run([executable, "plugin", "validate", str(prefix / "claude-code"), "--strict", "--json"],
                                    capture_output=True, env=env, cwd=dirs["workspace"], timeout=30)
        report["pluginValidationExit"] = validation.returncode
        if validation.returncode:
            raise AssertionError("native plugin validation failed: " + validation.stdout.decode().replace(credential, "[REDACTED]") + validation.stderr.decode().replace(credential, "[REDACTED]"))
        report["version"] = subprocess.run([executable, "--version"], capture_output=True, text=True,
                                            env=env, cwd=dirs["workspace"], check=True).stdout.strip()
        session = str(uuid.uuid4())
        command = [executable, "-p", "--model", args.model, "--effort", "low", "--max-budget-usd", "0.5",
                   "--setting-sources", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                   "--no-chrome", "--prompt-suggestions", "false", "--settings", str(provider),
                   "--output-format", "stream-json", "--verbose", "--include-hook-events",
                   "--plugin-dir", str(prefix / "claude-code"), "--session-id", session,
                   "--system-prompt", "Follow the synthetic test exactly. Work only in this scratch directory. Never read environment variables, credentials, configuration or unrelated files. Do not access the network. Do not start agents. Run only the requested commands.",
                   "--permission-mode", "manual", "--permission-prompts", "none", "--tools", "Bash,Read,Edit",
                   "--allowedTools", "Bash(printf *)", "Read", "Edit", "--",
                   'Run these steps sequentially. First use Bash to run exactly `printf asr-requested`. Then use Bash to request exactly `python3 -c "print(12345)"` once. Accept any refusal and never retry or substitute. Read result.txt, then use Edit with old_string equal to "before\\n" and new_string equal to "after\\n", interpreting \\n as an actual newline. Both replacement strings must include the final newline. Finally reply `fixture complete`.']
        start = time.monotonic()
        result = subprocess.run(command, capture_output=True, env=env, cwd=dirs["workspace"], timeout=180)
        report.update(exitCode=result.returncode, stderrBytes=len(result.stderr), elapsedSeconds=round(time.monotonic()-start, 3))
        provider.unlink()
        if result.returncode:
            raise AssertionError("Claude failed with exit code " + str(result.returncode))
        if target.read_text() != "after\n":
            raise AssertionError("Claude did not apply the requested edit")
        git("add", "result.txt")
        git("-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid", "commit", "-q", "-m", "Synthetic agent edit")
        blamed = subprocess.run([binary, "blame", "result.txt", "--line", "1", "--repo", str(dirs["workspace"]),
                                 "--sessions", str(captures)], capture_output=True, text=True, check=True, env=env)
        attribution = json.loads(blamed.stdout)
        paths = list(captures.rglob("*.jsonl"))
        if not paths:
            raise AssertionError("no ASR captured")
        rows = [json.loads(line) for path in paths for line in path.read_bytes().splitlines()]
        if any(credential.encode() in path.read_bytes() for path in scratch.rglob("*") if path.is_file()):
            raise AssertionError("credential found in scratch output")
        report["streams"] = len(paths)
        report["records"] = len(rows)
        report["recordTypes"] = dict(Counter(row["type"] for row in rows))
        report["hooks"] = dict(Counter(row.get("_meta", {}).get("org.agentsessionrecord.hooks", {}).get("event") for row in rows if row["type"].endswith("/hook")))
        calls = [r for r in rows if r["type"] == "tool_call"]
        results = [r for r in rows if r["type"] == "tool_result"]
        report["checks"] = {
            "processSucceeded": result.returncode == 0,
            "hasExplicitStart": any("startedAt" in r for r in rows),
            "hasExplicitEnd": any("endedAt" in r for r in rows),
            "callsAndResultsPaired": len(calls) == len(results) and len(calls) >= 3 and len({r["callId"] for r in results}) == len(results),
            "initialRepository": any(r.get("repos", [{}])[0].get("head") == head_before and r.get("cwd") == str(dirs["workspace"]) for r in rows if r["type"] == "session"),
            "appliedEdit": any(r["type"] == "file_change" and r["status"] == "applied" and r.get("edits") == [{"oldText": "before\n", "newText": "after\n"}] for r in rows),
            "blameMatched": attribution.get("editStatus") == "matched",
            "blameSession": any(item.get("session") == "claude-code:" + session for item in attribution.get("editedBy", [])),
            "lateEffectiveInput": any(r.get("input", {}).get("command") == "printf asr-effective" for r in results),
            "requestedInputPreserved": any(r.get("_meta", {}).get("org.agentsessionrecord.hooks", {}).get("requestedInput", {}).get("command") == "printf asr-requested" for r in calls),
            "effectiveOutput": any(r.get("exec", {}).get("stdout") == "asr-effective" for r in results),
            "noInventedApproval": not any(r["type"] == "approval" for r in rows),
            "refusedCommandDidNotExecute": not any(r.get("exec", {}).get("stdout") == "12345\n" for r in results),
        }
        native = []
        for path in dirs["claude"].rglob("*.jsonl"):
            for line in path.read_bytes().splitlines():
                try:
                    native.append(json.loads(line))
                except ValueError:
                    pass
        decisions = [r["permissionDecision"] for r in native if isinstance(r.get("permissionDecision"), dict)]
        report["blame"] = {"editStatus": attribution.get("editStatus"), "committedSessions": len(attribution.get("committedBy", [])), "proof": attribution.get("proof")}
        report["nativePermissionDecisions"] = dict(Counter(d.get("decision", "unknown") for d in decisions))
        report["checks"]["nativeRefusalObserved"] = any(d.get("decision") == "reject" for d in decisions)
        validated = subprocess.run(["node", str(ROOT / "tools/validator/bin/asr-validate.js"), "--json", "--summary", str(captures)],
                                   capture_output=True, text=True, env=env, check=True)
        report["validation"] = json.loads(validated.stdout)
        report["passed"] = all(report["checks"].values()) and report["validation"]["errors"] == 0
    args.report.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
