# Cline native Agent Session Record export

Export a saved session in an open format that search and code history tools can read. The export keeps the source facts available for later review.

Applies to upstream commit `46996c9992d91e57c268091c971cfda52b0da399`.
The local patch adds a format to the existing CLI history export.

```sh
git am patches/0001-native-agent-session-export.patch
cline history export SESSION_ID --format agent-session
cline history export SESSION_ID --format agent-session --output ./session.jsonl
```

Without an output path, the command writes one session to standard output.
An output path names a file. HTML remains the default format. Diagnostics use
standard error and unavailable sessions fail. The command uses the local session
backend. Native session start, end and working directory fields are retained
when present. The command does not register a discovery file.

The exporter writes ASR 0.1 with `producer.method: "native"`. It preserves native
message order and exact text. It records tool requests and model-facing results.
Repeated results are folded at their final stored position. Unknown outcomes stay
unknown. It keeps recorded reasoning text and excludes opaque provider state.
It does not fetch links or read current files to reconstruct earlier work.

The patch declares missing approvals, policy history, offered tools, inference
settings, model-call boundaries, usage history, file changes, commits, subagents,
copies, instructions and native metadata. It does not infer model calls from
assistant replies or infer edits and commits from prose. User roles do not prove
human authorship. The patch uses deterministic record IDs where native IDs are
unavailable or collide. It rejects unsafe parsed numbers rather than rounding
native tool arguments. Quoted wide values stay strings.

Credential fields and common token forms are filtered. Affected records carry
`truncated: true` and the session declares `secrets` missing. Filtering and valid
ASR do not establish that a transcript is suitable to share.

This patch adds export only. Live ASR files, discovery registration, deletion
hooks, annotations and complete capture of historical settings are not included.
It needs no added production dependency. The fixture is synthetic.

Cline compaction summaries carry `origin: "compaction"` and a following gap.
The export reads the selected saved transcript. It does not traverse other saved
session snapshots or restore points.

## Validation

The SDK builds and the CLI type check passes. Six focused test files pass 47
tests. The new tests cover native IDs, repeated results, compaction, corrupt data,
wide arguments, credential exclusion and stdout command behavior. Existing HTML
and session tests pass. The packaged sample is replayed and validated in ASR CI.

A source CLI 3.0.74 scratch turn through a local OpenAI-compatible endpoint completed.
The patched CLI exported it. The stream had 3 records, zero errors and zero
warnings. The run used an isolated home and configuration, no account and no
nonlocal network access. Its private runtime configuration is not packaged.

```sh
cd apps/cli
bun run test:unit src/session/__tests__/agent-session.test.ts \
  src/commands/history-asr.test.ts src/commands/history-command.test.ts \
  src/session/session.test.ts src/session/export.test.ts src/commands/history.test.ts
```

## Verification scope

The live evidence above is from a prior revision. The current source has focused
regressions and package checks. Its full agent and model path has not been rerun.
