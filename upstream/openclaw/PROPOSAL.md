---
summary: "Native OpenClaw export for Agent Session Record 0.1"
read_when:
  - Reviewing the native ASR export proposal
title: "Agent Session Record export"
---

# Agent Session Record export

Export a saved session in an open format that search and code history tools can read. The export keeps the source facts available for later review.

This proposal adds native ASR 0.1 export for OpenClaw SQLite session windows.
It applies to upstream commit `15e4d849d5f9a3559132454aeff90fe54781dee9`.
The supported source is OpenClaw 2026.10.7 at that commit.

```sh
openclaw sessions export --format agent-session --agent main --all --output ./asr
openclaw sessions export --format agent-session --session <native-session-id>
openclaw sessions export --format agent-session --session-key <routing-key> --output ./asr
```

Choose native session IDs, one routing key or all sessions. Multiple sessions
require a directory. A single session can go to standard output.
Diagnostics go to standard error. Destinations must be new.
Files use mode 600 and directories use mode 700. Add `--write-discovery` to
write the optional source discovery file.

The exporter uses the existing read-only snapshot owners. It records messages,
tool calls and results, explicit model-call IDs, inclusive usage, offered tools,
configured reasoning changes and recorded approval decisions.
Verified tool receipts can establish applied file changes.

Native sequence order controls output. Each tool result appears where its final update was recorded.
It retains earlier facts that the final update does not replace.
Snapshot approvals go immediately before their result. Inferences use the final
observation time. An identified call can omit its unknown model and declare that
loss. Configured reasoning clears use JSON null. Large native numbers become
exact strings inside structured arguments and metadata. Unsafe core counts stay
in native metadata and are omitted from numeric core fields.

The exporter does not reconstruct missing prompts, full policy history, served
models, call settings, attachment bytes or shell edits. Current side-store values
are labeled snapshots. A result with no independent argument observation adds
no effective input. Requested and served models remain separate.
PostgreSQL, cold archive bodies and legacy JSONL import are outside this patch.
The stream lists known losses.

Run the focused exporter tests through the repository test wrapper. Run targeted
type, lint and format checks for the changed modules. Set `ASR_VALIDATOR` to
the reference validator CLI for fixture validation.

```sh
node scripts/run-vitest.mjs src/sessions/agent-session-export.test.ts
```

Synthetic regressions and a fresh scratch session against a local OpenAI-compatible endpoint exercise the
export. The current reference validator reported zero errors for the exported
sample and scratch session.

## Patch package

`manifest.json` records the upstream base, refreshed implementation revision, ordered
patch commits and SHA-256 digests. The patch includes the native exporter and its
integration tests. Apply it in a clean checkout at the recorded upstream base.

```sh
git am /path/to/asr/upstream/openclaw/patches/*.patch
```

Run the package checks from the ASR repository root.

```sh
node upstream/openclaw/check.mjs
```

The retained sample is synthetic. `validation.json` contains aggregate sample and
scratch-session results. No real session text is included.

To reproduce the sample, set `ASR_PACKAGE` to this package's absolute path and
`SCRATCH` to a new private scratch directory. Run from the patched checkout
with its supported Node runtime and installed dependencies.

```sh
node --import ./scripts/tsx.mjs "$ASR_PACKAGE/reproduce-native.mjs" \
  "$ASR_PACKAGE/samples/native/source.json" "$SCRATCH/session.jsonl"
```

The sample and live stream have zero validator warnings.

## Verification scope

The live evidence above is from a prior revision. The current source has focused
regressions and package checks. Its full agent and model path has not been rerun.

The eight commits separate these review steps:

1. Record types, JSON boundaries and tool mappings.
2. Native transcript and side-store evidence mappings.
3. Read-only session snapshots and export output.
4. Synthetic session fixtures.
5. CLI wiring and command registration tests.
6. Exporter boundary tests.
7. Provider reasoning summaries and their regression.
8. Opt-in discovery and its regression.

Each commit adds fewer than 900 lines. The final source tree is identical to the
validated implementation tree. Discovery does not change reasoning mappings.
It contains no proposal document, knip configuration or fixture utility script.
The full CLI was not rebuilt for this revision, so live status remains partial.
