#!/usr/bin/env python3
"""Replay a bounded, private sample of recorded Claude edits in a scratch repo.

Only counts leave the temporary directory. No model requests are made. Native
file paths are redirected into the scratch repo. Original and replacement text
stay private. Cases with possible credentials are excluded before writing.
"""
import argparse
from collections import Counter
from datetime import datetime
import difflib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

class ReplayFailure(Exception):
    def __init__(self, code, counts):
        self.code, self.counts = code, counts


ROOT = Path(__file__).resolve().parents[3]
SENSITIVE = re.compile(
    r"(?i)password|credential|secret|bearer|api.?key|access.?token|auth.?token|"
    r"session.?token|refresh.?token|private.?key|github_pat_|gh[pousr]_|sk-|"
    r"AKIA|ASIA|xox[baprs]-|https?://[^\s/@]+:[^\s/@]+@|"
    r"[A-Za-z0-9_+/=-]{48,}"
)


def run(*args, cwd=ROOT, at=None):
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
           "GIT_AUTHOR_NAME": "Scratch Replay", "GIT_AUTHOR_EMAIL": "test@example.invalid",
           "GIT_COMMITTER_NAME": "Scratch Replay", "GIT_COMMITTER_EMAIL": "test@example.invalid"}
    if at is not None:
        env.update(GIT_AUTHOR_DATE=f"@{int(at)} +0000", GIT_COMMITTER_DATE=f"@{int(at)} +0000")
    if args[0] == "git":
        args = ("git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", *args[1:])
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError("scratch_command_failed")
    return result.stdout


def sample(source, max_files, max_sessions, max_edits, counts):
    files = sorted(source.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    cases, sessions, selected = [], set(), set()
    for path in files[:max_files]:
        if len(cases) >= max_edits or len(sessions) >= max_sessions:
            break
        if path.stat().st_size > 128 * 1024 * 1024:
            counts["oversize_files_skipped"] += 1
            continue
        counts["source_files_read"] += 1
        calls = {}
        with path.open() as stream:
            for line in stream:
                if len(cases) >= max_edits:
                    break
                try:
                    record = json.loads(line)
                except (ValueError, UnicodeError):
                    counts["malformed_source_lines"] += 1
                    continue
                message = record.get("message", {})
                content = message.get("content", []) if isinstance(message, dict) else []
                if not isinstance(content, list):
                    continue
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "tool_use":
                        calls[part.get("id")] = (record, part)
                output = record.get("toolUseResult")
                if not isinstance(output, dict) or not isinstance(record.get("sessionId"), str):
                    continue
                results = [p for p in content if isinstance(p, dict) and p.get("type") == "tool_result"]
                if len(results) != 1 or results[0].get("is_error") is True or output.get("staged") is True:
                    continue
                call = calls.get(results[0].get("tool_use_id"))
                if not call or call[1].get("name") != "Edit" or not isinstance(call[0].get("message", {}).get("id"), str):
                    continue
                try:
                    at = datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00")).timestamp()
                except (KeyError, ValueError, TypeError):
                    counts["untimed_edits_skipped"] += 1
                    continue
                before, old, new = (output.get(k) for k in ("originalFile", "oldString", "newString"))
                if not all(isinstance(s, str) for s in (old, new)) or not old or old == new:
                    continue
                if isinstance(before, str):
                    counts["edit_results_with_original"] += 1
                elif before is None:
                    counts["edit_results_without_original"] += 1
                    # Retain the real recorded replacements, but use a controlled
                    # scratch baseline when no historical full file was captured.
                    # The converted record still has originalFile: null.
                    hunks = output.get("structuredPatch", [])
                    sparse = {}
                    valid = bool(hunks)
                    for hunk in hunks:
                        start = hunk.get("oldStart", 0)
                        lines = hunk.get("lines", [])
                        if not isinstance(start, int) or not 1 <= start <= 20000 or not isinstance(lines, list):
                            valid = False
                            break
                        old_lines = [line[1:] for line in lines if isinstance(line, str) and line.startswith((" ", "-"))]
                        if hunk.get("oldLines") != len(old_lines) or start + len(old_lines) > 20000:
                            valid = False
                            break
                        for i, text in enumerate(old_lines, start - 1):
                            if i in sparse and sparse[i] != text:
                                valid = False
                            sparse[i] = text
                    if not valid or not sparse:
                        counts["missing_patch_context_skipped"] += 1
                        continue
                    before = "".join(sparse.get(i, f"# scratch padding {i}") + "\n" for i in range(max(sparse) + 1))
                else:
                    continue
                if SENSITIVE.search(before + old + new + json.dumps(call[1].get("input", {})) + json.dumps(output.get("structuredPatch", []))):
                    counts["sensitive_cases_skipped"] += 1
                    continue
                occurrences = sum(before.startswith(old, i) for i in range(len(before)))
                if occurrences != 1 and not (occurrences and output.get("replaceAll") is True):
                    counts["ambiguous_cases_skipped"] += 1
                    continue
                after = before.replace(old, new) if output.get("replaceAll") else before.replace(old, new, 1)
                a, b = before.splitlines(keepends=True), after.splitlines(keepends=True)
                added = [j + 1 for tag, _, _, start, end in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
                         if tag in ("insert", "replace") for j in range(start, end)
                         if b[j].strip() and b.count(b[j]) == 1 and b[j] not in a]
                if not added:
                    counts["no_distinct_added_lines"] += 1
                    continue
                identity = (record["sessionId"], call[1].get("id"))
                request_identity = (record["sessionId"], call[0].get("uuid"))
                if identity in selected or request_identity in selected:
                    counts["duplicate_observations_skipped"] += 1
                    continue
                selected.update((identity, request_identity))
                cases.append((record, call, results[0], before, after, added[:3]))
                sessions.add(record["sessionId"])
    counts["sample_sessions"] = len(sessions)
    return cases


def check(binary, source, max_files=1000, max_sessions=12, max_edits=30):
    counts = Counter(model_requests=0, correct_lines=0, unknown_lines=0, wrong_lines=0, missed_agent_lines=0)
    cases = sample(source, max_files, max_sessions, max_edits, counts)
    if not cases:
        raise RuntimeError("no_eligible_recorded_edits")
    times = [datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00")).timestamp() for record, *_ in cases]
    with tempfile.TemporaryDirectory(prefix="asr-private-claude-") as temp:
        scratch = Path(temp)
        repo = scratch / "repo"
        repo.mkdir()
        run("git", "init", "-q", cwd=repo)
        native = {}
        for i, (record, (request, part), result, before, after, added) in enumerate(cases):
            file = repo / f"case-{i}.txt"
            file.write_text(before)
            output = {k: record["toolUseResult"][k] for k in
                      ("oldString", "newString", "originalFile", "structuredPatch", "replaceAll", "userModified")
                      if k in record["toolUseResult"]}
            output["filePath"] = str(file)
            inp = {k: v for k, v in part.get("input", {}).items() if k in ("old_string", "new_string", "replace_all")}
            inp["file_path"] = str(file)
            sid = record["sessionId"]
            native.setdefault(sid, []).extend([
                {"type": "assistant", "timestamp": request.get("timestamp", record["timestamp"]), "uuid": request["uuid"], "sessionId": sid, "cwd": str(repo),
                 "message": {**{k: v for k, v in request["message"].items() if k in ("id", "model")},
                             "role": "assistant", "content": [{"type": "tool_use", "id": part["id"], "name": part["name"], "input": inp}]}},
                {"type": "user", "timestamp": record["timestamp"], "uuid": record["uuid"], "sessionId": sid, "cwd": str(repo), "toolUseResult": output,
                 "message": {"role": "user", "content": [{k: v for k, v in result.items() if k in ("type", "tool_use_id", "is_error")}]}},
            ])
            output.setdefault("originalFile", None)
            counts["sample_edits"] += 1
            counts["sample_with_original" if isinstance(output["originalFile"], str) else "sample_without_original"] += 1
            counts["edits_without_trailing_newline"] += not output["newString"].endswith("\n")
            counts["multiline_edits"] += "\n" in output["newString"]
        run("git", "add", ".", cwd=repo)
        run("git", "commit", "-qm", "Scratch baseline", cwd=repo, at=min(times) - 60)
        source_dir = scratch / "native"
        source_dir.mkdir()
        for i, records in enumerate(native.values()):
            (source_dir / f"session-{i}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
        out = scratch / "converted"
        summary = json.loads(run(str(binary), "convert", "--agent", "claude-code", str(source_dir), "--out", str(out)))
        counts["converted_sessions"] = summary["sessions"]
        validation = json.loads(run("node", str(ROOT / "tools/validator/bin/asr-validate.js"), "--json", "--summary", str(out)))
        counts["validation_errors"] = validation["errors"]
        counts["validation_warnings"] = validation["warnings"]
        for i, (_, _, _, _, after, _) in enumerate(cases):
            (repo / f"case-{i}.txt").write_text(after)
        run("git", "add", ".", cwd=repo)
        run("git", "commit", "-qm", "Scratch recorded edits", cwd=repo, at=max(times) + 60)
        for i, (record, (_, part), _, _, _, added) in enumerate(cases):
            for line in added:
                result = json.loads(run(str(binary), "blame", f"case-{i}.txt", "--line", str(line), "--repo", str(repo), "--sessions", str(out)))
                counts["queried_lines"] += 1
                citation = result["editedBy"][0].get("call") if result["editStatus"] == "matched" else None
                correct = isinstance(citation, str) and citation.endswith("#" + part["id"])
                if correct:
                    counts["correct_lines"] += 1
                elif result["editStatus"] == "unknown":
                    counts["unknown_lines"] += 1
                    counts["missed_agent_lines"] += 1
                else:
                    counts["wrong_lines"] += 1
        # A person later changes the same lines while retaining the replacement
        # snippets. These must never inherit the session's earlier edit credit.
        for i, (_, _, _, _, after, added) in enumerate(cases):
            lines = after.splitlines(keepends=True)
            for line in added:
                text = lines[line - 1]
                lines[line - 1] = text.rstrip("\r\n") + "  # scratch person note" + ("\n" if text.endswith("\n") else "")
            (repo / f"case-{i}.txt").write_text("".join(lines))
        run("git", "add", ".", cwd=repo)
        run("git", "commit", "-qm", "Scratch later person edits", cwd=repo, at=max(times) + 120)
        for i, (_, _, _, _, _, added) in enumerate(cases):
            for line in added:
                result = json.loads(run(str(binary), "blame", f"case-{i}.txt", "--line", str(line), "--repo", str(repo), "--sessions", str(out)))
                counts["queried_lines"] += 1
                counts["person_lines"] += 1
                counts["unknown_lines" if result["editStatus"] == "unknown" else "wrong_lines"] += 1
        if counts["wrong_lines"] or counts["validation_errors"]:
            raise ReplayFailure("scratch_replay_failed", dict(counts))
    counts["scratch_removed"] = True
    return dict(counts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--max-files", type=int, default=1000)
    parser.add_argument("--max-sessions", type=int, default=12)
    parser.add_argument("--max-edits", type=int, default=30)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        counts = check(args.binary.resolve(), args.source, args.max_files, args.max_sessions, args.max_edits)
    except ReplayFailure as error:
        print(json.dumps({"error": error.code, "counts": error.counts}))
        raise SystemExit(1) from None
    except Exception as error:
        # Exceptions can contain native values. Keep all failure output private.
        print(json.dumps({"error": "private_replay_failed", "code": type(error).__name__}))
        raise SystemExit(1) from None
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
