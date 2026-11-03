# Entire checkpoint importer

Read saved sessions from a local `entire/checkpoints/v1` branch into ASR.
The importer reads Git objects. It does not check out the branch, fetch, run
hooks, read working files named by transcripts or execute recorded commands.

The storage profile is pinned to Entire CLI v0.12.2.
The raw transcript adapters cover Claude Code JSONL and Codex rollout JSONL,
including the synthetic native samples in this repository.
Other native agent formats remain visible as metadata gaps.

Live test: passed for the released Entire v0.12.2 CLI with scripted synthetic
Claude Code hooks and a local Git commit. No account or model request was used.
The imported four-record session has zero validation errors and warnings.
This tests Entire's actual checkpoint writer. It does not claim a live agent run.
See [live-test.json](live-test.json) for counts.

## Install and use

From the repository root, with Python 3.11 or later, uv and Git:

```sh
uv sync --all-packages
uv run --all-packages asr-import-entire /work/repository --output-dir /work/asr
node tools/validator/bin/asr-validate.js /work/asr
```

The local branch must already exist. No credentials or Entire installation are
needed for import. `--namespace` is available when source session IDs repeat.
Output names are hashes of agent identity and the verbatim native session ID.
Each native session gets one private file. Existing files are never overwritten.
The hash is a filename, not a replacement session identity.

## Storage and evidence

The reader resolves the local branch once, then reads its immutable tree.
It follows checkpoint summary pointers inside each checkpoint subtree and
rejects traversal and pointers outside that subtree.
It reads session metadata and authoritative `full.jsonl`, including numbered
raw chunks. It supports the legacy single-session root layout too.
It does not use the compact transcript, which can be a checkpoint delta.

Whole-session prefix snapshots merge into one session without repeated model
usage. Native UUID snapshots complete at their last retained observation.
Distinct Claude assistant blocks sharing a provider message ID form one
inference, with usage from its last contributing observation.
Anthropic input totals include base input plus supplied cache reads and writes.
Codex `token_usage_record.response_id` identifies individual calls.
Its input and output totals already include cache and reasoning subsets.
Repeated native response IDs are counted once.

Divergent retained snapshots keep additional native work and declare unresolved
cross-checkpoint order. Conflicting native revisions stay in metadata gaps.
Checkpoint ordering uses local branch history. Timestamps do not reorder events.
Only snapshots retained at the branch tip are read. Replaced or deleted
checkpoint history is a declared loss.

Checkpoint `created_at`, branch, model labels, file lists and commit associations
stay in metadata. They do not establish session start, applied edits or commit
actions. Whole-checkpoint statistics are never added to per-call usage.
No file diff is synthesized from the repository or a file list.
Metadata attribution, compact transcripts, task sidecars, assets and unsupported
native events remain declared losses. Full approval and copy detection is not
available. Tool requests and available model-facing results stay searchable.
See the [shared safety rules](../vendor-core/README.md#safety-and-losses).

## Checks and local reproduction

```sh
uv run --all-packages pytest importers/entire/tests
uv run --all-packages python importers/entire/tools/live_test.py \
  --entire /work/bin/entire --output-dir /work/live-asr \
  --summary /work/live-summary.json
```

The live runner needs the released v0.12.2 binary and new output paths.
It creates and removes a throwaway Git repository and private runtime config.
Telemetry and automatic session uploads are disabled.
It seeds the update cache and directs outbound proxy traffic to a closed local
port. It never signs in or sends a model request.

The [native metadata](tests/fixtures/metadata.json) and
[raw transcript](tests/fixtures/full.jsonl) are synthetic.
The [ASR sample](tests/fixtures/full.expected.asr.jsonl) shows the raw mapping.
Tests cover checkpoint snapshots, chunks, missing transcripts, multiple sessions,
path traversal, retained branches and the checked-in native agent samples.

Sources: [Entire v0.12.2 storage architecture](https://github.com/entireio/cli/blob/v0.12.2/docs/architecture/sessions-and-checkpoints.md)
and [checkpoint metadata types](https://github.com/entireio/cli/blob/v0.12.2/api/checkpoint/metadata.go).
