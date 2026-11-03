#!/usr/bin/env python3
"""Seeded edit interleavings with an independent per-line ownership oracle.

Only synthetic data is used. Git repositories and ASR streams are temporary.
Every emitted stream is validated in one batch before it is removed. A fixed
wall-time budget and per-command timeouts keep the CI check bounded.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import difflib
import json
import os
from pathlib import Path
import random
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]
BASE = 1767225600


def timestamp(at):
    return datetime.fromtimestamp(at, timezone.utc).isoformat()


def run(args, repo, at=BASE, author=None):
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
           "GIT_AUTHOR_NAME": "Synthetic", "GIT_COMMITTER_NAME": "Synthetic",
           "GIT_AUTHOR_EMAIL": "test@example.invalid", "GIT_COMMITTER_EMAIL": "test@example.invalid",
           "GIT_AUTHOR_DATE": f"@{at if author is None else author} +0000",
           "GIT_COMMITTER_DATE": f"@{at} +0000"}
    if args[0] == "git":
        args = ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", *args[1:]]
    result = subprocess.run(args, cwd=repo, env=env, capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise AssertionError(f"synthetic command failed: {args[0]}: {result.stderr}")
    return result.stdout.strip()


def change(old, new, shape, before, after, line, at, event):
    r = {"type": "file_change", "id": f"edit-{event}", "path": "file.py",
         "op": "modify", "status": "applied", "ts": timestamp(at)}
    if shape == "write":
        r.update(before={"text": before}, after={"text": after})
    elif shape == "codex":
        r["patch"] = "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), n=1))
    else:
        r["edits"] = [{"oldText": old, "newText": new}]
        if shape == "claude-original":
            r["before"] = {"text": before}
        elif shape == "claude-context":
            # Real Claude result shape, with surrounding lines and positions.
            a, b = before.splitlines(), after.splitlines()
            lo, hi = max(0, line - 3), min(len(a), line + 4)
            lines = [" " + s for s in a[lo:line]] + ["-" + a[line], "+" + b[line]] + [" " + s for s in a[line + 1:hi]]
            r["_meta"] = {"com.anthropic.claude-code": {"result": {
                "originalFile": None, "structuredPatch": [{"oldStart": lo + 1, "oldLines": hi - lo,
                    "newStart": lo + 1, "newLines": hi - lo, "lines": lines}]}}}
    return r


def history(rng, number, repo, streams, binary, counts):
    repo.mkdir()
    run(["git", "init", "-q", "--initial-branch=main"], repo)
    size = rng.randrange(3, 7)
    lines = [f"flag_{i} = False\n" for i in range(size)]
    baseline = "".join(lines)
    owners = [None] * size
    seen = [{line} for line in lines]
    (repo / "file.py").write_text(baseline)
    run(["git", "add", "."], repo)
    run(["git", "commit", "-qm", "Synthetic baseline"], repo)
    base = run(["git", "rev-parse", "HEAD"], repo)
    sessions = []
    for sid in range(3):
        h = {"type": "session", "id": "header", "formatVersion": "0.1",
             "agent": {"name": "com.example.generator"}, "sessionId": f"history-{number}-{sid}",
             "cwd": str(repo), "repos": [{"path": str(repo)}],
             "producer": {"name": "synthetic-generator", "version": "1", "method": "native"}}
        if sid == 2:
            h["parent"] = {"kind": "subagent", "session": f"com.example.generator:history-{number}-0"}
        sessions.append([h])
    skew = [rng.choice([0, 0, -600, 600, 3600, -3600]) for _ in sessions]
    counts["skewed_histories"] += any(skew)
    shapes = ["claude-context", "claude-original", "claude-bare", "whole-line", "codex", "write"]
    events = rng.randrange(2, 10)
    for event in range(events):
        line = rng.randrange(size)
        actor = rng.choice([None, 0, 1, 2])
        old_line = lines[line]
        # Values repeat to exercise undo/re-add sequences. No-op writes keep
        # their previous owner because they introduce no new committed bytes.
        value = rng.choice(["False", "True", str(event + 2)])
        new_line = f"flag_{line} = {value}\n"
        if old_line == new_line:
            continue
        before = "".join(lines)
        lines[line] = new_line
        after = "".join(lines)
        owners[line] = actor
        counts["undo_edits"] += new_line in seen[line]
        seen[line].add(new_line)
        if actor is None:
            counts["person_edits"] += 1
            continue
        shape = rng.choice(shapes)
        counts[shape] += 1
        counts["subagent_edits"] += actor == 2
        old, new = old_line, new_line
        if shape in ("claude-bare", "claude-context", "claude-original"):
            old, new = old_line.split(" = ")[1].strip(), value
        sessions[actor].append(change(old, new, shape, before, after, line,
            BASE + 120 + event * 60 + skew[actor], event))
    final = "".join(lines)
    # Ensure every repository has a changed commit even if the random walk
    # ended back at its starting tree.
    if final == baseline:
        lines[0] = "flag_0 = person_final\n"
        owners[0] = None
        final = "".join(lines)
    (repo / "file.py").write_text(final)
    run(["git", "add", "."], repo)
    commit_at = BASE + 180 + events * 60
    run(["git", "commit", "-qm", "Synthetic interleaving"], repo, commit_at)
    original = run(["git", "rev-parse", "HEAD"], repo)
    # Post-commit round trips should never acquire credit for existing lines,
    # even after a date-preserving rewrite and with a skewed agent clock.
    if rng.randrange(3) == 0:
        line, actor = rng.randrange(size), rng.randrange(3)
        before = final
        transient = lines.copy()
        transient[line] = f"flag_{line} = transient\n"
        middle = "".join(transient)
        for n, (a, b, old, new) in enumerate([(before, middle, lines[line], transient[line]),
                                              (middle, before, transient[line], lines[line])]):
            shape = rng.choice(["claude-original", "claude-context", "codex", "whole-line"])
            sessions[actor].append(change(old, new, shape, a, b, line,
                commit_at + 60 + n * 60 + skew[actor], events + n))
        counts["postcommit_roundtrips"] += 1
    rewrite = rng.choice(["none", "amend", "rebase", "cherry-pick"])
    counts[rewrite] += 1
    if rewrite == "amend":
        run(["git", "commit", "--amend", "-qm", "Synthetic amended message"], repo, commit_at + 300)
    elif rewrite in ("rebase", "cherry-pick"):
        run(["git", "checkout", "-qb", "upstream", base], repo)
        (repo / "other.txt").write_text("unrelated\n")
        run(["git", "add", "."], repo)
        run(["git", "commit", "-qm", "Synthetic upstream"], repo, BASE + 60)
        if rewrite == "cherry-pick":
            run(["git", "cherry-pick", original], repo, commit_at + 300)
        else:
            run(["git", "checkout", "-q", "main"], repo)
            run(["git", "rebase", "upstream"], repo, commit_at + 300)
    own_streams = streams / str(number)
    own_streams.mkdir()
    for sid, records in enumerate(sessions):
        (own_streams / f"{sid}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    for line in range(size):
        result = json.loads(run([str(binary), "blame", "file.py", "--line", str(line + 1),
                                "--repo", str(repo), "--sessions", str(own_streams)], repo))
        expected = None if owners[line] is None else f"com.example.generator:history-{number}-{owners[line]}"
        matches = result["editedBy"]
        counts["queried_lines"] += 1
        if not matches:
            counts["unknown"] += 1
        elif all(e["session"] == expected for e in matches):
            counts["correct"] += 1
        else:
            counts["wrong"] += 1
            raise AssertionError(f"seeded history {number}, line {line + 1}, expected {expected}, result {result}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--histories", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=600601)
    parser.add_argument("--seconds", type=int, default=900)
    args = parser.parse_args()
    if args.histories < 2000:
        parser.error("at least 2000 histories are required")
    started = time.monotonic()
    counts = Counter(correct=0, unknown=0, wrong=0, histories=0)
    rng = random.Random(args.seed)
    with tempfile.TemporaryDirectory(prefix="asr-generated-") as directory:
        scratch = Path(directory)
        streams = scratch / "streams"
        streams.mkdir()
        for number in range(args.histories):
            if time.monotonic() - started > args.seconds:
                raise AssertionError("generated history time budget exceeded")
            history(rng, number, scratch / f"repo-{number}", streams, args.binary.resolve(), counts)
            counts["histories"] += 1
            if (number + 1) % 200 == 0:
                print(json.dumps({"progress": number + 1, **{key: counts[key]
                    for key in ("correct", "unknown", "wrong")}}), flush=True)
        validation = json.loads(run(["node", str(ROOT / "tools/validator/bin/asr-validate.js"),
                                     "--json", "--summary", str(streams)], ROOT))
        assert validation["errors"] == 0, validation
        counts["validation_errors"] = validation["errors"]
        counts["validation_warnings"] = validation["warnings"]
        assert counts["correct"] > 0, "all-unknown attribution is not a passing generator"
        assert counts["wrong"] == 0
        for kind in ["claude-bare", "claude-context", "claude-original", "codex", "whole-line", "write",
                     "person_edits", "subagent_edits", "undo_edits", "amend", "rebase", "cherry-pick",
                     "skewed_histories", "postcommit_roundtrips"]:
            assert counts[kind] > 0, f"missing generated coverage: {kind}"
    counts.update(seed=args.seed)
    result = dict(counts)
    result.update(correct_rate=counts["correct"] / counts["queried_lines"],
                  unknown_rate=counts["unknown"] / counts["queried_lines"], scratch_removed=True,
                  elapsed_seconds=round(time.monotonic() - started, 2))
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
