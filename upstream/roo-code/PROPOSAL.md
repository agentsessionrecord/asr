# Roo Code native Agent Session Record export

Export a saved session in an open format that search and code history tools can read. The export keeps the source facts available for later review.

Applies to upstream commit `b867ec9145750d0ae1ff7f02d35406e9bf2a0b16`.
The local patch adds a format choice to the existing task export action.

```sh
git am patches/0001-native-agent-session-export.patch
```

Build the extension in the usual way. Open a task and use its export action.
Select **Agent Session Record** and save the `.jsonl` file. Markdown is also
available. Missing, corrupt or non-array task history fails before the save dialog
can write an empty successful export. No CLI or discovery command is advertised.

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

The export uses Roo's `ApiMessage` type. It retains condensed and truncated native
branches in stored order. A summary has a following gap when its replaced history
is not retained. Reasoning summaries and encrypted markers remain distinct.
An absent native `is_error` leaves result status unknown.

## Validation

The exporter and existing Markdown tests pass 22 tests with the project's Vitest
configuration and network-disabled setup. A focused type check uses the exact
native `ApiMessage` alias and passes. The changed provider module compiles in a
focused Bun build. The complete extension and UI were not built or driven.
The packaged native fixture is replayed and its ASR sample validates with zero
errors and warnings.

Roo was not live-tested. This patch integrates with a VS Code extension host and
task history. No configured extension host or account was used. Fixture tests
cover the native content mapping. Provider wiring received a focused compile
check. A real extension-host export
remains a review step.

```sh
cd src
pnpm exec vitest run integrations/misc/__tests__/agent-session.test.ts \
  integrations/misc/__tests__/export-markdown.spec.ts
```
