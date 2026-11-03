# Native session export for Goose

Export a saved session in an open format that search and code history tools can read. The export keeps the source facts available for later review.

This patch adds Agent Session Record export to Goose 1.57.0. It applies to
`090dedb7625c8aadb9bb05d68028fd00f36b429e` from
<https://github.com/block/goose>. The patch and commit digests are in
[manifest.json](manifest.json).

Apply the patch in a clean checkout of that commit with `git am`.

```sh
goose sessions export --format agent-session --session SESSION_ID
goose sessions export --format agent-session --session SESSION_ID --output exports
```

The first command writes one JSONL stream to stdout. The second writes a file in
the chosen directory and reports its path on stderr. The filename is a digest of
the native session ID. An explicit session ID or name is required. This patch
supports one session at a time. It does not add `--since` or bulk selection.

The export reads persisted messages in insertion order, even when clocks move
backward. It keeps text and content order, tool calls, model-facing tool results,
reasoning and explicit tool confirmation responses. Repeated tool results are
folded at the last stored position, with gaps for earlier updates. Native message
IDs survive when one message produces one record. Expanded records get stable
derived IDs. Large native numbers become strings.

Goose session IDs can repeat across installations. The exporter persists a
generated installation namespace in its data directory and includes it in every
header. Keep that file when moving an installation. Each export ends with the
latest stored title, mode and requested-model snapshot. Those values do not
establish earlier settings or the model that answered each turn.

The export declares missing history and other unavailable facts. It does not
invent inference boundaries, usage, exit codes, file edits, commits, copied
history or subagent relationships. It excludes elicitation answers and known
secret patterns. It cannot restore text already sanitized by native storage or
recover hidden history. It does not register discovery files, append a live
sidecar or add deletion hooks.

Tool outcomes follow the recorded flag. `true` means failed and `false` means
completed. An absent flag leaves the outcome unknown.

The patch includes seven Rust tests and a synthetic native fixture. Tests cover
storage ordering, final results, explicit approval, secret exclusion, stable IDs
and large numbers. They also cover absent and explicit outcome flags.
The CLI was built and checked with Clippy. A scratch session
ran through a OpenAI-compatible or Anthropic-compatible endpoint, then the real CLI exported its persisted
history. Both the sample and live export pass the ASR validator without errors
or warnings. Details are in `check.mjs`.

The package checks in `scripts/ci.sh` validate the synthetic sample, compare it
with native evidence, and check patch syntax and provenance. They do not compile
Goose. Run the included Rust tests when applying the patch upstream.

`live-test.recipe.yaml` holds the synthetic prompt for an isolated live
check. It belongs to this package and does not change Goose's self-test recipe.
Configure a private local provider before running it. No live run is part of
the package check.

## Verification scope

The live evidence above is from a prior revision. The current source has focused
regressions and package checks. Its full agent and model path has not been rerun.
