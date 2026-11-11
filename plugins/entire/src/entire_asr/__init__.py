"""The entire-asr external command for the Entire CLI.

Entire runs `entire-asr` for `entire asr ...` with the remaining arguments,
the user's working directory and ENTIRE_REPO_ROOT when it runs inside a Git
repository. Exit codes reach the caller unchanged.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import signal
import sys
import tempfile

from asr_entire import Session, convert, discover, output_name, write_all
from asr_entire.store import Reader, git, repository_root

VERSION = "0.1.0"
SHORT = "Export Entire checkpoints as Agent Session Record (ASR) files"
LONG = """Reads Entire checkpoints from this repository's Git objects and writes one
Agent Session Record (ASR) file per agent session. It reads the git-refs backend
(refs/entire/checkpoints/<shard>/<id>) and the git-branch backend
(entire/checkpoints/v1). It never checks out, fetches, pushes or changes
checkpoint data, and never runs recorded commands."""
EXPORT_SHORT = "Write ASR files for selected checkpoint sessions"
EXPORT_LONG = """Selects sessions by checkpoint, commit or session ID and writes each session
as one ASR file. A file holds the whole retained session from every local
checkpoint of that session, and each record names the checkpoint whose slice
first held it. Selections add up.

Without --out, a single selected session is written to stdout. With --out,
one file per session is written to that directory and each path is printed.
Existing files are never overwritten.

The normalized transcript (transcript.jsonl) is the main source and covers
every agent Entire supports. --transcript full reads the raw Claude Code or
Codex transcript (full.jsonl) instead, which keeps reasoning text."""
EXPORT_EXAMPLE = """  entire asr export --checkpoint 01KVBJCWYA4YW6J5M9GP655HZN > session.jsonl
  entire asr export --commit HEAD --out asr
  entire asr export --session 3f2a --out asr
  entire asr export --all --out asr"""
GUIDANCE = """Use it when a task needs the agent sessions behind checkpoints or commits in a
portable format, for review, audit or another tool. It only reads checkpoint
data. It writes only the files it reports. Run it from inside the repository."""
FLAGS = [
    ("all", "", "bool", "", "Export every session in this repository's local checkpoints"),
    ("checkpoint", "c", "string", "", "Export the sessions in a checkpoint (ID or prefix). Repeatable"),
    ("commit", "", "string", "", "Export the sessions linked to a commit (SHA or ref). Repeatable"),
    ("namespace", "", "string", "", "Installation namespace for session IDs that repeat across machines"),
    ("out", "o", "string", "", "Directory for one ASR file per session (default: stdout for one session)"),
    ("session", "", "string", "", "Export a session (ID or prefix). Repeatable"),
    ("transcript", "", "string", "auto", "Transcript to read: auto, normalized or full"),
]
TRAILER = re.compile(r"^Entire-Checkpoint:[ \t]*(\S+)[ \t]*$", re.M)


class UsageError(Exception):
    pass


def flag_table(flags) -> str:
    rows = []
    for name, short, kind, default, usage in [*flags, ("help", "h", "bool", "", "help for this command")]:
        head = (f"  -{short}, --{name}" if short else f"      --{name}") + ("" if kind == "bool" else " " + kind)
        tail = usage + (f' (default "{default}")' if default else "")
        rows.append((head, tail))
    width = max(len(head) for head, _ in rows) + 3
    return "\n".join(head.ljust(width) + tail for head, tail in rows)


def root_help() -> str:
    return f"""{LONG}

Usage:
  entire asr [command]

Available Commands:
  export      {EXPORT_SHORT}
  agent-help  Machine-readable usage for coding agents
  version     Show the entire-asr version

Flags:
  -h, --help      help for asr
  -v, --version   version for asr

Use "entire asr [command] --help" for more information about a command.
"""


def export_help() -> str:
    return f"""{EXPORT_LONG}

Usage:
  entire asr export [flags]

Examples:
{EXPORT_EXAMPLE}

Flags:
{flag_table(FLAGS)}
"""


def agent_help(path: list[str], as_json: bool) -> str:
    if path not in ([], ["export"]):
        raise UsageError(f'unknown command "{" ".join(path)}" for "entire asr"')
    if path == ["export"]:
        doc = {"command": "entire asr export", "short": EXPORT_SHORT, "long": EXPORT_LONG, "guidance": GUIDANCE,
               "example": EXPORT_EXAMPLE,
               "flags": [{"name": name, **({"shorthand": short} if short else {}), "type": kind,
                          **({"default": default} if default else {}), "usage": usage}
                         for name, short, kind, default, usage in FLAGS]}
    else:
        doc = {"command": "entire asr", "short": SHORT, "long": LONG, "guidance": GUIDANCE,
               "subcommands": [{"name": "export", "short": EXPORT_SHORT, "audience": "task-driven"}]}
    if as_json:
        return json.dumps(doc, indent=2) + "\n"
    text = f"{doc['command']} - {doc['short']}\n{doc['long']}\n\nWhen to use this:\n{doc['guidance']}\n"
    if "example" in doc:
        text += f"\nExamples:\n{doc['example']}\n\nFlags:\n{flag_table(FLAGS)}\n"
    else:
        text += ("\nSubcommands: export\n             export writes files: run it when the task calls for it\n"
                 "Next:  entire agent-help asr <subcommand>\n")
    return text


def parse_export(args: list[str]) -> dict:
    options = {"all": False, "checkpoint": [], "commit": [], "session": [], "namespace": None, "out": None,
               "transcript": "auto", "help": False}
    names = {"--" + name: name for name, *_ in FLAGS} | {"-c": "checkpoint", "-o": "out", "-h": "help", "--help": "help"}
    index = 0
    while index < len(args):
        arg = args[index]
        flag, _, inline = arg.partition("=") if arg.startswith("--") else (arg, "", "")
        name = names.get(flag)
        if name is None:
            raise UsageError(f"unknown flag: {arg}" if arg.startswith("-") else f'unexpected argument "{arg}"')
        if name in ("all", "help"):
            if inline:
                raise UsageError(f"flag --{name} takes no value")
            options[name] = True
        else:
            if not inline:
                index += 1
                if index >= len(args):
                    raise UsageError(f"flag needs an argument: {flag}")
                inline = args[index]
            if isinstance(options[name], list):
                options[name].append(inline)
            else:
                options[name] = inline
        index += 1
    if options["transcript"] not in ("auto", "normalized", "full"):
        raise UsageError('--transcript must be "auto", "normalized" or "full"')
    if not options["help"] and not (options["all"] or options["checkpoint"] or options["commit"] or options["session"]):
        raise UsageError("choose sessions with --checkpoint, --commit, --session or --all")
    return options


def match(values: set[str], prefix: str, label: str) -> str:
    if prefix in values:
        return prefix
    found = [value for value in values if value.startswith(prefix)]
    if not found:
        raise UsageError(f"no local {label} matches {prefix}")
    if len(found) > 1:
        raise UsageError(f"{label} prefix {prefix} matches {len(found)} {label}s")
    return found[0]


def commit_checkpoints(repo: Path, ref: str) -> tuple[str, set[str]]:
    if not ref or ref.startswith("-"):
        raise UsageError(f"not a commit: {ref}")
    try:
        sha = git(repo, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}").decode().strip()
        message = git(repo, "cat-file", "commit", sha).decode("utf-8", "replace")
    except ValueError:
        raise UsageError(f"not a commit: {ref}") from None
    body = message.split("\n\n", 1)[1] if "\n\n" in message else ""
    return sha, set(TRAILER.findall(body))


def select(repo: Path, sessions: list[Session], options: dict) -> list[Session]:
    if options["all"]:
        return sessions
    chosen: dict[int, Session] = {}
    checkpoints = {checkpoint for session in sessions for checkpoint in session.checkpoints}
    for prefix in options["checkpoint"]:
        checkpoint = match(checkpoints, prefix, "checkpoint")
        chosen |= {id(s): s for s in sessions if checkpoint in s.checkpoints}
    for ref in options["commit"]:
        sha, trailers = commit_checkpoints(repo, ref)
        found = [s for s in sessions if trailers & set(s.checkpoints) or any(
            isinstance(link, dict) and link.get("sha") == sha
            for entry in s.entries for link in entry.summary.get("linked_commits") or [])]
        if not found:
            raise UsageError(f"no local checkpoint session is linked to commit {sha}")
        chosen |= {id(s): s for s in found}
    ids = {s.session_id for s in sessions}
    for prefix in options["session"]:
        session = match(ids, prefix, "session")
        chosen |= {id(s): s for s in sessions if s.session_id == session}
    return [s for s in sessions if id(s) in chosen]


def export(args: list[str]) -> int:
    options = parse_export(args)
    if options["help"]:
        sys.stdout.write(export_help())
        return 0
    root = os.environ.get("ENTIRE_REPO_ROOT")
    try:
        repo = Path(root) if root else repository_root(Path.cwd())
    except ValueError:
        raise UsageError("not inside a Git repository") from None
    reader = Reader(repo)
    sessions = select(repo, discover(repo, reader), options)
    if not sessions:
        raise UsageError("this repository has no local Entire checkpoints")
    if options["out"] is None and len(sessions) > 1:
        raise UsageError(f"{len(sessions)} sessions selected: pass --out DIR to write one file each")
    invoked = {"command": "entire-asr", "version": VERSION}
    if os.environ.get("ENTIRE_CLI_VERSION"):
        invoked["entireCliVersion"] = os.environ["ENTIRE_CLI_VERSION"]
    streams = [(convert(s, reader, namespace=options["namespace"], transcript=options["transcript"], invoked=invoked), s)
               for s in sessions]
    if options["out"] is None:
        with tempfile.TemporaryDirectory(prefix="entire-asr-") as temporary:
            output = Path(temporary) / "session.jsonl"
            streams[0][0].write(output)
            sys.stdout.buffer.write(output.read_bytes())
        return 0
    directory = Path(options["out"])
    prepared = [(stream, directory / output_name(session)) for stream, session in streams]
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    for path in write_all(prepared):
        print(path)
    return 0


def run(argv: list[str]) -> int:
    command, rest = (argv[0], argv[1:]) if argv else ("", [])
    if command in ("", "-h", "--help", "help") and not rest:
        sys.stdout.write(root_help())
        return 0
    if command == "help" and rest == ["export"]:
        sys.stdout.write(export_help())
        return 0
    if command in ("version", "-v", "--version"):
        print(f"entire-asr {VERSION}")
        return 0
    if command == "agent-help":
        as_json = "--json" in rest
        path = [arg for arg in rest if arg != "--json"]
        if any(arg.startswith("-") for arg in path):
            raise UsageError("agent-help takes a command path, not flags")
        sys.stdout.write(agent_help(path, as_json))
        return 0
    if command == "export":
        return export(rest)
    raise UsageError(f'unknown command "{command}" for "entire asr"')


def main():
    try:
        code = run(sys.argv[1:])
    except UsageError as error:
        print(f"Error: Invalid usage: {error}", file=sys.stderr)
        print('Run "entire asr --help" for usage.', file=sys.stderr)
        code = 1
    except (ValueError, OSError, TypeError, UnicodeError) as error:
        detail = str(error) if isinstance(error, ValueError) else type(error).__name__
        print(f"Error: export failed: {detail}", file=sys.stderr)
        code = 1
    except KeyboardInterrupt:
        # Terminate by the signal so an enclosing shell loop stops too.
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        os.kill(os.getpid(), signal.SIGINT)
        code = 130
    try:
        sys.stdout.flush()
    except BrokenPipeError:
        code = code or 1
    sys.exit(code)


if __name__ == "__main__":
    main()
