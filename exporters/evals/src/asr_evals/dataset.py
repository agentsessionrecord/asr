"""Build eval rows without promoting guesses into reference answers."""

import difflib
import shlex
from pathlib import PurePosixPath

from .model import content, pick, record_view
from .reader import stable_id


def task_prompt(session):
    for record in session.records:
        if record["type"] != "message" or record.get("role") != "user" or not session.original(record):
            continue
        parts = []
        for part in record.get("content", []):
            author = part.get("author", record.get("author"))
            origin = part.get("origin", record.get("origin"))
            if part.get("type") == "text" and author == "human" and origin in ("prompt", "queued", "command", "scheduled", "external", None):
                parts.append(part["text"])
        if parts:
            return {"text": "".join(parts), "reference": session.cite(record), "truncated": record.get("truncated", False)}
    return None


def _path(session, path):
    if not isinstance(path, str) or not path or any(ord(c) < 32 or c in '\\"' for c in path):
        return None
    candidate = PurePosixPath(path)
    if ".." in candidate.parts:
        return None
    if candidate.is_absolute():
        cwd = session.header.get("cwd")
        if not cwd:
            return None
        try:
            candidate = candidate.relative_to(cwd)
        except ValueError:
            return None
    return str(candidate) if str(candidate) != "." else None


def final_diff(session):
    changes = [r for r in session.records if r["type"] == "file_change" and session.original(r) and r.get("status") not in ("proposed", "failed")]
    if not changes:
        return None, "no_applied_edit_evidence"
    states = {}
    for change in changes:
        path = _path(session, change.get("path"))
        if change.get("status") != "applied" or change.get("truncated") or path is None or change.get("op") not in ("add", "modify", "delete"):
            return None, "incomplete_or_unsupported_edit_chain"
        before = "" if change["op"] == "add" else change.get("before", {}).get("text")
        after = "" if change["op"] == "delete" else change.get("after", {}).get("text")
        if not isinstance(before, str) or not isinstance(after, str):
            return None, "full_snapshots_unavailable"
        if path in states and states[path][1] != before:
            return None, "discontinuous_edit_chain"
        if path not in states:
            states[path] = [before, after, change["op"] == "add", change["op"] == "delete"]
        else:
            states[path][1], states[path][3] = after, change["op"] == "delete"
    patches = []
    for path, (before, after, added, deleted) in states.items():
        lines = difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                     fromfile="/dev/null" if added else "a/" + path,
                                     tofile="/dev/null" if deleted else "b/" + path)
        for line in lines:
            patches.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    return "".join(patches), "observed_snapshot_chain"


def _test_command(call, result, session):
    command = result.get("exec", {}).get("command")
    if command is None:
        effective = session.effective_input(call)
        arguments = effective.get("input")
        command = arguments.get("command") if isinstance(arguments, dict) else effective.get("inputText")
    try:
        words = shlex.split(command) if isinstance(command, str) else command
        if not isinstance(words, list) or not words or not all(isinstance(w, str) for w in words):
            return False
        name = PurePosixPath(words[0]).name
        return name in ("pytest", "jest", "vitest", "tox") or (name in ("python", "python3") and words[1:3] in (["-m", "pytest"], ["-m", "unittest"])) or (name in ("npm", "pnpm", "yarn", "cargo", "go") and len(words) > 1 and words[1] == "test")
    except ValueError:
        return False


def rows(sessions, annotations=(), include_content=False, test_tools=()):
    output = []
    for session in sessions:
        prompt = task_prompt(session)
        diff, diff_basis = final_diff(session)
        tests, changes = [], []
        for record in session.records:
            if not session.original(record):
                continue
            if record["type"] == "file_change":
                changes.append(record_view(session, record, include_content))
            if record["type"] != "tool_call":
                continue
            result = session.result(record)
            if result is None or not session.original(result):
                continue
            if record.get("name") in test_tools or _test_command(record, result, session):
                item = {"source": "session_tool", "reference": session.cite(result),
                        "call": session.cite(record), "tool_status": result["status"], "test_status": None,
                        "exec": pick(result.get("exec", {}), ("exitCode", "signal"))}
                if include_content:
                    item["exec"] = result.get("exec", {})
                    if "content" in result:
                        item["content"] = content(result["content"])
                tests.append(item)
        targets = {session.ref} | {session.cite(r) for r in [session.header] + session.records}
        for annotation in annotations:
            if annotation["kind"] == "test" and annotation["session"] in targets:
                if annotation["data"].get("status") not in ("passed", "failed"):
                    continue
                tests.append({"source": "annotation", "annotation_id": annotation["id"], "target": annotation["session"],
                              "test_status": annotation["data"]["status"],
                              "learned_at": annotation.get("at"), "data": annotation["data"]})
        repos = [pick(repo, ("path", "head", "branch")) for repo in session.header.get("repos", [])]
        starting_commit = repos[0].get("head") if len(repos) == 1 else None
        missing = []
        if prompt is None:
            missing.append("task_prompt_unknown")
        if starting_commit is None:
            missing.append("starting_commit_unknown")
        if diff is None:
            missing.append(diff_basis)
        if not tests:
            missing.append("test_results_unknown")
        output.append({"id": stable_id(session.ref), "input": {
            "task_prompt": prompt["text"] if prompt is not None and include_content else None,
            "starting_commit": starting_commit, "starting_repositories": repos},
            "expected": {"final_diff": diff if include_content else None, "test_results": tests},
            "metadata": {"asr_session": session.ref, "source_sha256": session.digest,
                         "prompt_reference": prompt["reference"] if prompt else None,
                         "prompt_truncated": prompt["truncated"] if prompt else None,
                         "content_included": include_content, "missing": sorted(session.missing),
                         "unknown": missing, "final_diff_basis": diff_basis,
                         "final_diff_scope": "observed_session_edits_not_verified_commit_diff",
                         "file_changes": changes, "accounting": session.accounting()}})
    return output
