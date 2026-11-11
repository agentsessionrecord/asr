# Entire external command

`entire asr` exports Entire checkpoints as Agent Session Record (ASR) files.
It is an external command for the Entire CLI. When you run `entire asr`,
Entire finds the `entire-asr` executable on `PATH` or in its managed plugin
directory and runs it with the remaining arguments.

The command uses the [Entire checkpoint importer](../../importers/entire/README.md)
for all reading and mapping. It is tested with Entire CLI v0.13.2.

## Install

With Python 3.11 or later, uv and Git:

```sh
uv tool install "git+https://github.com/agentsessionrecord/asr#subdirectory=plugins/entire"
entire asr --help
```

uv puts `entire-asr` on your `PATH`, which is enough for Entire to find it.
To link it into Entire's managed plugin directory instead, run
`entire plugin install "$(command -v entire-asr)"`.

## Usage

Run it inside a repository that has Entire checkpoints:

```sh
entire asr export --checkpoint 01KVBJCWYA4YW6J5M9GP655HZN > session.jsonl
entire asr export --commit HEAD --out asr
entire asr export --session 3f2a --out asr
entire asr export --all --out asr
```

| Flag | Meaning |
| --- | --- |
| `-c, --checkpoint ID` | Sessions in a checkpoint, by ID or unique prefix |
| `--commit REF` | Sessions linked to a commit by its `Entire-Checkpoint` trailer or a recorded commit link |
| `--session ID` | A session, by ID or unique prefix |
| `--all` | Every session in the repository's local checkpoints |
| `-o, --out DIR` | Write one file per session to `DIR` and print each path |
| `--transcript auto` | `normalized` reads `transcript.jsonl`. `full` reads the Claude Code or Codex `full.jsonl`, which keeps reasoning text |
| `--namespace NAME` | Installation namespace for session IDs that repeat across machines |

Selections add up, and the selection flags can repeat. Without `--out`, one
selected session is written to standard output. Existing files are never
overwritten. Each file holds the whole retained session from every local
checkpoint of that session, and each record names the checkpoint whose slice
first held it.

`entire asr --help` and `entire asr export --help` print help.
`entire agent-help asr` and `entire agent-help asr export` describe the
command to coding agents, with `--json` for a structured form.
`entire asr version` prints the version.

The command exits with 0 on success and 1 on an error, and Entire passes the
code on. Errors are printed to standard error. Interrupting it stops it by the
same signal.

## Repository and environment

Entire runs the command in your working directory and sets `ENTIRE_REPO_ROOT`
when it runs inside a Git repository. The command reads that repository. Run
directly as `entire-asr`, it uses the Git repository of the working directory.
It needs no variables beyond the ones Entire passes to every external command,
and no account or network access.

## What it reads

The command reads Git objects only. It reads the git-refs backend,
`refs/entire/checkpoints/<shard>/<id>`, and the git-branch backend,
`entire/checkpoints/v1`, from local refs. It reads each session's metadata and
its normalized transcript, `transcript.jsonl`, which covers every agent Entire
supports. It reads `full.jsonl` only for the `full` choice, or when a Claude
Code or Codex session has no normalized transcript. It never checks out,
fetches, pushes or changes checkpoint data, and never runs hooks or recorded
commands. It writes only the files it reports.

The importer README lists the mapping and the [known losses](../../importers/entire/README.md#known-losses).

## Checks

```sh
uv run --all-packages pytest plugins/entire/tests
```

The tests run the command against synthetic checkpoint stores and validate its
output. The [live test](../../importers/entire/live-test.json) ran it through
the released Entire v0.13.2 CLI, after `entire plugin install`, on both backends.
