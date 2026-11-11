# Entire checkpoint importer

Read Entire checkpoints from a repository's Git objects into ASR.
The importer reads both checkpoint backends and every agent that Entire's
normalized transcript covers. It does not check out, fetch, run hooks, read
working files or execute recorded commands.

The storage and transcript profile is pinned to Entire CLI v0.13.2.
The [Entire external command](../../plugins/entire/README.md) runs this
importer as `entire asr export`.

Live test: passed. The released Entire v0.13.2 CLI recorded a scripted Claude
Code session on each backend, and a real Claude Code session and a real Codex
session with live model calls through a loopback endpoint. Every export has
zero validation errors and warnings. See [live-test.json](live-test.json).

## Install and use

From the repository root, with Python 3.11 or later, uv and Git:

```sh
uv sync --all-packages
uv run --all-packages asr-import-entire /work/repository --output-dir /work/asr
node tools/validator/bin/asr-validate.js /work/asr
```

No credentials or Entire installation are needed for import. Each native
session gets one private file. Existing files are never overwritten.
Output names are hashes of agent identity and the verbatim native session ID.
The hash is a file name, not a replacement session identity.
`--namespace` is available when source session IDs repeat.
`--transcript` chooses the source. `auto` is the default. `normalized` reads
only `transcript.jsonl`. `full` reads the raw Claude Code or Codex `full.jsonl`.

## Storage

Entire stores checkpoints in one of two backends. The importer reads both in
the same run.

| Backend | Where | Checkpoint IDs |
| --- | --- | --- |
| git-refs, the default for new setups | One ref per checkpoint, `refs/entire/checkpoints/<shard>/<id>`, whose commit tree is the checkpoint | ULIDs, or hex IDs migrated from the branch |
| git-branch | The local branch `entire/checkpoints/v1`, with each checkpoint under `<id[:2]>/<id[2:]>/` | 12-character hex |

The shard is the last two characters of the ID. A ref whose shard does not
match its ID is ignored, as Entire ignores it. The reader resolves each ref
once and reads its tree. It follows the session pointers in each checkpoint's
`metadata.json` and rejects traversal and pointers outside that checkpoint.
When one checkpoint exists in both backends after a migration, the ref copy is
read, as Entire's readers do. The branch copy is named in header metadata.

A checkpoint can hold several sessions. One session can span many
checkpoints. The importer groups sessions by agent and native session ID, so
each session becomes one file.

## The normalized transcript

`transcript.jsonl` is the main source. It is the Entire Transcript Format v1,
which Entire writes for Claude Code, Codex, Copilot CLI, Cursor, Droid,
OpenCode, Pi and Antigravity. Older Gemini CLI checkpoints map too.
An external agent's session uses the agent name
`org.agentsessionrecord.entire-unknown`, and its native agent name stays in
header metadata.

Each checkpoint stores the whole session up to that point. Its
`compact_transcript_start` marks where its own slice begins. The importer
orders a session's checkpoints by Entire's position markers, then by creation
time. It checks that each later transcript restates the earlier lines before
its marker. Entire's marker can repeat one merged line from the previous
checkpoint, and the check allows that. The later view then replaces the
earlier one. A tool result that arrived after a commit is kept, and no line or
usage is counted twice. Each record names, in metadata, the checkpoint whose
slice first held it.

A later view can leave out earlier lines, as after an abandoned Pi branch or
an OpenCode revert. The earlier lines then follow a gap at the end of the file,
and `checkpoint_order` is declared. A checkpoint without the marker comes from
Entire before 0.8 and holds only its own lines. Those are joined in order, and
`checkpoint_deltas` is declared. A checkpoint with no `transcript.jsonl` is
covered by a later checkpoint. Without one, a gap marks it.

## Mapping

| Normalized line | ASR |
| --- | --- |
| `user` line | `message` with role `user` |
| `assistant` text and images | `message` with role `assistant` |
| `tool_use` block | `tool_call` with its ID, name and input |
| Inlined tool `result` | `tool_result` right after its call |
| One model call | `inference` with model and usage |
| Unknown block or line type | gap or loss, with the native value in metadata |

User messages have no author or origin. The format does not mark injected
text or compaction summaries, so `message_origin` is declared.
Entire writes `success` when the agent reported no error. The importer keeps
that as `completed`, and `error` becomes `failed`. An empty output becomes a
result without content. A Read or Edit result's file path becomes the call's
location. Images keep their MIME type and inline data. Images that Entire moved
to checkpoint assets keep only the MIME type, and `assets` is declared.

Model calls come only from the format's own call boundaries. Claude Code lines
that share a message ID form one call, and a later line with that ID and its own
usage starts another. A Codex line with usage closes one call. Each Pi
assistant line is one call. Copilot CLI, Cursor, Droid, OpenCode, Antigravity
and external agents record counts per message or none, so their counts stay in
metadata and `usage` and `model` stay declared.

Claude Code, Codex and Pi lines from Entire 0.12.2 or later count fresh input
apart from cache reads and writes. ASR input is their sum. Older lines hold
fresh input only, or input with an unknown cache share, so `inputTokens` is
left out for them. Reasoning tokens are part of output tokens. Claude Code
lines name the model that served the call, which becomes `model.id`. Codex and
Pi lines name the configured model, which becomes `model.requested`.
`usage` and `model` leave the declared losses only when every inference
record has them.

## Known losses

| Loss | Why |
| --- | --- |
| `reasoning` | Entire's converters drop thinking blocks |
| `content` | User text is trimmed and IDE context tags are removed |
| `message_origin` | Injected text and compaction summaries are not marked |
| `tool_output` | A result is one text string. Claude Code Bash results hold stdout only |
| `timestamps` | Tool results have no time of their own |
| `subagents` | Task transcripts under `tasks/` are not read. A subagent ID stays in result metadata |
| `checkpoint_history` | Only ref tips are read. Earlier versions of a ref and deleted checkpoints are not |
| `checkpoint_attribution` | Entire's line attribution metadata is not mapped |
| `exit_codes`, `file_changes`, `commits`, `approvals`, `agent_settings`, `tools` | The format does not carry them |

No file change or commit action is derived from tool input, file lists,
checkpoint metadata or `Entire-Checkpoint` trailers. Checkpoint creation time,
branch, model labels, token totals and commit links stay in header metadata.
They do not set session times or per-call usage.

## Raw transcript adapters

The Claude Code and Codex adapters read the raw `full.jsonl`. They keep
reasoning text, compaction summaries and native record IDs, which the
normalized transcript drops. `--transcript full` uses them for those two
agents. `auto` uses them only when the latest checkpoint of a Claude Code or
Codex session has no `transcript.jsonl`, as with checkpoints from Entire before
0.7.8 or a normalized transcript over Entire's 50 MB limit.
Current Codex rollouts record commands and file changes as item events. The
raw Codex adapter keeps those only as metadata, so the normalized transcript
maps more of a Codex session's tool calls.

`full.jsonl` is a whole-session snapshot, including numbered chunks.
Snapshots that extend each other merge without repeated usage. Divergent
snapshots keep additional native work and declare unresolved order.
Distinct Claude assistant blocks sharing a provider message ID form one
inference, with usage from its last contributing observation. Anthropic input
totals include base input plus supplied cache reads and writes. Codex
`token_usage_record.response_id` identifies individual calls, and repeated
response IDs are counted once.

## Safety

The reader runs Git read commands with inherited Git variables, replace refs,
hooks and the file system monitor turned off. Each blob is capped at 32 MiB and
each session at 128 MiB of checkpoint data. See the
[shared safety rules](../vendor-core/README.md#safety-and-losses).

## Checks and local reproduction

```sh
uv run --all-packages pytest importers/entire/tests plugins/entire/tests
uv tool install ./plugins/entire
uv run --all-packages python importers/entire/tools/live_test.py \
  --entire /work/bin/entire --plugin "$(command -v entire-asr)" \
  --output-dir /work/live-asr --summary /work/live-summary.json
```

The live runner needs the released v0.13.2 binary and new output paths.
For each backend it creates and removes a throwaway repository, home directory
and runtime config. It records a scripted Claude Code session across two
commits, imports it, installs the external command into Entire's plugin
directory and runs `entire asr export`. Telemetry and session uploads are off.
It seeds the update cache and sends outbound proxy traffic to a closed local
port. It never signs in or sends a model request.

All fixtures are synthetic. The
[checkpoint store](tests/fixtures/checkpoints.json) holds four agents across
both backends, a checkpoint migrated from the branch, a multi-session
checkpoint, a straddling message, a late tool result and a divergent view.
Each [normalized transcript](tests/fixtures/normalized/) has its ASR mapping
beside it. The [raw transcript](tests/fixtures/full.jsonl) and its
[ASR sample](tests/fixtures/full.expected.asr.jsonl) show the raw adapter.

Sources: [Entire v0.13.2 sessions and checkpoints](https://github.com/entireio/cli/blob/v0.13.2/docs/architecture/sessions-and-checkpoints.md),
[ref checkpoint backend](https://github.com/entireio/cli/blob/v0.13.2/docs/architecture/ref-checkpoint-backend.md),
[Entire Transcript Format](https://github.com/entireio/cli/blob/v0.13.2/transcript/README.md)
and [checkpoint metadata types](https://github.com/entireio/cli/blob/v0.13.2/api/checkpoint/metadata.go).
