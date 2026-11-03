#!/usr/bin/env python3
"""Exercise conversion, validation, a Git commit and line attribution offline."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]


def run(*args, cwd=ROOT):
    if args[0] == "git":
        args = ("git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgSign=false", *args[1:])
    result = subprocess.run(args, cwd=cwd, env={
        **os.environ,
        "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z" if "Baseline" in args else "2026-01-01T00:10:00Z",
        "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z" if "Baseline" in args else "2026-01-01T00:10:00Z",
        "GIT_AUTHOR_NAME": "Synthetic",
        "GIT_AUTHOR_EMAIL": "synthetic@example.invalid",
        "GIT_COMMITTER_NAME": "Synthetic",
        "GIT_COMMITTER_EMAIL": "synthetic@example.invalid",
    }, capture_output=True, text=True, check=True)
    return result.stdout


def check(binary):
    with tempfile.TemporaryDirectory(prefix="asr-blame-check-") as scratch:
        scratch = Path(scratch)
        repo = scratch / "project"
        repo.mkdir()
        run("git", "init", "-q", cwd=repo)
        (repo / "baseline.txt").write_text("baseline\n")
        run("git", "add", "baseline.txt", cwd=repo)
        run("git", "commit", "-qm", "Baseline", cwd=repo)
        native = scratch / "native.jsonl"
        native.write_text("".join(json.dumps(r) + "\n" for r in [
            {"type": "session_meta", "payload": {"id": "synthetic-blame", "cwd": str(repo)}},
            {"timestamp": "2026-01-01T00:05:00Z", "type": "event_msg", "payload": {"type": "item_completed", "item": {
                "type": "FileChange", "id": "synthetic-edit", "name": "apply_patch",
                "status": "completed", "changes": {
                    "result.txt": {"type": "add", "content": "recorded new line\n"}
                },
            }}},
        ]))
        converted = scratch / "converted"
        conversion = json.loads(run(str(binary), "convert", "--agent", "codex", str(native), "--out", str(converted)))
        assert conversion["sessions"] == 1
        stream = next(converted.glob("*.jsonl"))
        validation = json.loads(run("node", str(ROOT / "tools/validator/bin/asr-validate.js"), "--json", str(stream)))
        assert validation["errors"] == 0, validation["counts"]
        records = [json.loads(line) for line in stream.read_text().splitlines()]
        change = next(r for r in records if r["type"] == "file_change")
        (repo / "result.txt").write_text(change["after"]["text"])
        run("git", "add", "result.txt", cwd=repo)
        run("git", "commit", "-qm", "Apply recorded edit", cwd=repo)
        blame = json.loads(run(str(binary), "blame", "result.txt", "--line", "1", "--repo", str(repo), "--sessions", str(converted)))
        expected = "codex:synthetic-blame#" + change["id"]
        assert blame["editStatus"] == "matched" and blame["editedBy"][0]["reference"] == expected
        assert blame["committedBy"] == [] and blame["proof"] is False
        return {
            "synthetic": True,
            "modelRequests": 0,
            "pipeline": ["convert", "validate", "git-commit", "blame"],
            "sessions": conversion["sessions"],
            "validationErrors": validation["errors"],
            "validationWarnings": validation["warnings"],
            "validationCodes": validation["counts"],
            "matchedLines": len(blame["editedBy"]),
            "commitCredits": len(blame["committedBy"]),
            "sourceErrors": blame["sourceErrors"],
            "proof": blame["proof"],
            "readerSha256": hashlib.sha256((ROOT / "crates/asr-cli/src/tools/blame.rs").read_bytes()).hexdigest(),
        }


def check_claude(binary):
    with tempfile.TemporaryDirectory(prefix="asr-claude-blame-check-") as scratch:
        scratch = Path(scratch)
        repo = scratch / "project"
        repo.mkdir()
        run("git", "init", "-q", cwd=repo)
        (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n\n# untouched context\n")
        run("git", "add", ".", cwd=repo)
        run("git", "commit", "-qm", "Baseline", cwd=repo)
        native = scratch / "native.jsonl"
        native.write_text((ROOT / "crates/asr-cli/tests/native/claude-edits.jsonl").read_text().replace("/work/app", str(repo)))
        out = scratch / "converted"
        summary = json.loads(run(str(binary), "convert", "--agent", "claude-code", str(native), "--out", str(out)))
        validation = json.loads(run("node", str(ROOT / "tools/validator/bin/asr-validate.js"), "--json", "--summary", str(out)))
        assert validation["errors"] == 0
        (repo / "calc.py").write_text("def add(a, b, c=0):\n    return a + b + c\n\n# untouched context\n")
        (repo / "created.py").write_text("# header\nvalue = 2\n\n# retained write line\nprint(value + 1)\n")
        run("git", "add", ".", cwd=repo)
        run("git", "commit", "-qm", "Recorded changes", cwd=repo)
        cases = [("calc.py", 1, "edit-1"), ("calc.py", 2, "edit-1"),
                 ("created.py", 1, "shift-1"), ("created.py", 2, "shift-1"),
                 ("created.py", 4, "write-1"), ("created.py", 5, "tail-1")]
        for file, line, call in cases:
            result = json.loads(run(str(binary), "blame", file, "--line", str(line), "--repo", str(repo), "--sessions", str(out)))
            assert result["editStatus"] == "matched", (file, line)
            assert result["editedBy"][0]["call"].endswith("#" + call)
            assert len(result["editedBy"][0]["prompts"]) == 1
            assert result["editedBy"][0]["model"]["value"] == "example-served-model"
        context = json.loads(run(str(binary), "blame", "calc.py", "--line", "4", "--repo", str(repo), "--sessions", str(out)))
        assert context["editStatus"] == "unknown"
        return {"synthetic": True, "modelRequests": 0, "sessions": summary["sessions"],
                "matchedLines": len(cases), "unchangedContextUnknown": True,
                "validationErrors": validation["errors"], "validationWarnings": validation["warnings"],
                "validationCodes": validation["counts"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = check(args.binary.resolve())
    report["claude"] = check_claude(args.binary.resolve())
    report["privateReplayHarness"] = json.loads(run(
        "python3", str(Path(__file__).with_name("check-private-claude.py")),
        "--binary", str(args.binary.resolve()), "--source", str(ROOT / "crates/asr-cli/tests/native"),
        "--max-files", "1", "--max-sessions", "1", "--max-edits", "1"))
    data = json.dumps(report, indent=2) + "\n"
    if args.report:
        args.report.write_text(data)
    print(data, end="")


if __name__ == "__main__":
    main()
