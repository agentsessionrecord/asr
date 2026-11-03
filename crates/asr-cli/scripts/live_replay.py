#!/usr/bin/env python3
"""Run synthetic replays through explicit private settings on the compatible endpoint."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from live_provider import loopback_endpoint

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--openai-model", default=os.environ.get("ASR_OPENAI_MODEL"))
    parser.add_argument("--openai-base-url", default=os.environ.get("ASR_OPENAI_BASE_URL"))
    parser.add_argument("--anthropic-base-url", default=os.environ.get("ASR_ANTHROPIC_BASE_URL"))
    parser.add_argument("--anthropic-model", default=os.environ.get("ASR_ANTHROPIC_MODEL"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if not args.openai_model and not args.anthropic_model:
        parser.error("at least one model is required")
    for protocol in ("openai", "anthropic"):
        if getattr(args, protocol + "_model"):
            loopback_endpoint(getattr(args, protocol + "_base_url"))
    root = Path(__file__).resolve().parents[3]
    binary = root / "target/debug/asr"
    results = {"synthetic": True, "endpointVerified": True, "runs": []}
    with tempfile.TemporaryDirectory(prefix="asr-replay-live-") as directory:
        scratch = Path(directory)
        os.chmod(scratch, 0o700)
        for protocol, model in [("openai", args.openai_model), ("anthropic", args.anthropic_model)]:
            if not model:
                continue
            settings = {"protocol": protocol, "baseUrl": loopback_endpoint(getattr(args, protocol + "_base_url"))}
            # Check the explicit route before loading a credential.
            loopback_endpoint(settings["baseUrl"])
            settings["apiKey"] = args.key_file.read_text().strip()
            config = scratch / f"{protocol}-provider.json"
            with open(config, "x", opener=lambda p, f: os.open(p, f, 0o600)) as file:
                json.dump(settings, file)
            source = scratch / f"{protocol}-source.jsonl"
            records = [
                {"type": "session", "id": "header", "formatVersion": "0.1", "agent": {"name": "com.example.agent"}, "sessionId": "synthetic-live", "producer": {"name": "synthetic", "version": "1", "method": "native"}},
                {"type": "session_info", "id": "tools", "tools": []},
                {"type": "message", "id": "prompt", "role": "user", "author": "human", "origin": "prompt", "content": [{"type": "text", "text": "Reply with the word ready."}]},
                {"type": "inference", "id": "selected", "model": {"requested": model}, "settings": {"maxOutputTokens": 128}},
            ]
            source.write_text("".join(json.dumps(record) + "\n" for record in records))
            output = scratch / f"{protocol}-run.jsonl"
            command = [str(binary), "replay", str(source), "--inference", "selected", "--provider-settings", str(config), "--out", str(output), "--variant", "synthetic-live"]
            completed = subprocess.run(command, cwd=root, capture_output=True, timeout=80)
            entry = {"protocol": protocol, "requestedModel": model, "exitCode": completed.returncode}
            if output.exists():
                run = [json.loads(line) for line in output.read_text().splitlines()]
                validation = subprocess.run(["node", "tools/validator/bin/asr-validate.js", "--json", str(output)], cwd=root, capture_output=True, timeout=20)
                inference = next(r for r in run if r["type"] == "inference" and "copiedFrom" not in r)
                entry.update({"records": len(run), "validationExitCode": validation.returncode, "modelReported": "id" in inference["model"], "usageReported": "usage" in inference, "failed": "error" in inference, "toolCalls": sum(r["type"] == "tool_call" for r in run), "toolResults": sum(r["type"] == "tool_result" for r in run)})
                if "error" in inference:
                    entry["httpStatus"] = inference["error"].get("code")
            config.unlink()
            settings.clear()
            results["runs"].append(entry)
    args.out.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))
    return int(any(r["exitCode"] or r.get("validationExitCode", 1) for r in results["runs"]))


if __name__ == "__main__":
    raise SystemExit(main())
