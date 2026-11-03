# Native session export for Hermes

Export a saved session in an open format that search and code history tools can read. The export keeps the source facts available for later review.

This patch adds Agent Session Record export to Hermes at
`c7c7e0fa92f40c8f526e4a52c0966c128245ffd3` from
<https://github.com/NousResearch/hermes-agent>. The patch and commit digests are in
[manifest.json](manifest.json).

Apply the patch in a clean checkout of that commit with `git am`.

```sh
hermes sessions export --format agent-session --session SESSION_ID
hermes sessions export --format agent-session --session SESSION_ID --output exports
hermes sessions export --format agent-session --output exports --since 2026-11-01T00:00:00Z
```

Exactly one explicit session is required for stdout. Repeat `--session` when
writing several files to a directory. With a directory and no session selector,
the command selects all sessions. `--since` filters by stored activity. Filenames
are digests of native session IDs. Diagnostics go to stderr. Unavailable or
ambiguous sessions fail. ASR export rejects upload, deletion, view filters and
logical-lineage options.

The exporter takes a read-only SQLite snapshot and reads messages in insertion
order. It keeps inactive and compacted stored rows, model-facing content,
reasoning and tool calls. It folds repeated tool results at their final stored
position and declares the earlier updates as gaps. Tool result status stays
unknown because the stored row does not prove an execution outcome. Native row
IDs survive as strings, with suffixes when a row expands. Large numbers in tool
input are encoded as strings without rounding their stored JSON literals.

Explicit branch and delegation markers establish parent relationships. Shared
message UIDs identify copies from a direct parent. Compaction summaries carry
harness authorship and a gap. The final snapshot records the latest title and
requested model. It does not claim historical model selection.

Known secrets are excluded with Hermes's forced redactor. Unsupported or corrupt
content produces a declared gap. Missing approval history, settings, tools,
usage, inference boundaries, exit codes, file changes and commits remain unknown.
The patch does not register discovery files, append a live sidecar or add
deletion hooks.

Seven focused tests passed through the repository test runner. All 14 repository
checks passed. A scratch agent session ran through a OpenAI-compatible or Anthropic-compatible endpoint, then the
real CLI exported its persisted history. Both the sample and live export pass
the ASR validator without errors or warnings. Details are in
`check.mjs`.

The package checks in `scripts/ci.sh` validate the synthetic sample, compare it
with native evidence, and check patch syntax and provenance. They do not install
Hermes. Run the included Python tests when applying the patch upstream.

## Verification scope

The live evidence above is from a prior revision. The current source has focused
regressions and package checks. Its full agent and model path has not been rerun.
