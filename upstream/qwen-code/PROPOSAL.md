# Native ASR export for Qwen Code

Export a saved session in an open format that search and code history tools can read. The export keeps the source facts available for later review.

This patch adds `qwen sessions export --format agent-session`. It exports saved
legacy transcripts without starting a model session.

It applies to upstream commit
`9ebd2de1713039b8cb5f60c9982e3d4c450e3a8b` from
<https://github.com/QwenLM/qwen-code>.

```sh
git am patches/0001-native-agent-session-export.patch
qwen sessions export --format agent-session --session SESSION_ID
qwen sessions export --format agent-session --input transcript.jsonl --session SESSION_ID
qwen sessions export --format agent-session --output exports
```

A single selector writes JSONL to standard output. Directory output supports
repeated selectors, hashes filenames and creates private files without replacing
existing output. `--since` selects by native file modification time. Default
source discovery uses the current project's active and archived transcripts.
Explicit input bypasses global configuration. Managed transaction journals are
refused because their protocol needs a separate mapping.

The exporter uses native `ChatRecord` types. It preserves text, tool arguments,
model-facing results, native IDs and all retained branches. Same-UUID fragments
are assembled at completion. Duplicate tool results fold once per call at the
last observation. Intervening messages retain their positions. Explicit human
provenance establishes human authorship. Recorded approval policies, prompt-time
approval modes, custom titles and explicit parent-session links are preserved.
Unknown native content stays in vendor content parts. Corruption creates gaps.
Known secrets and opaque provider state are excluded. Large native integers stay
exact strings.

Approval decisions, full settings, model-call accounting, file-change
normalization, commits, offered tools, complete instructions and copy detection
remain declared losses. Tool success does not imply approval. No inference is
invented from message boundaries. No current Git state or account identity is
borrowed as history. This patch does not write live ASR or install discovery
files. Full input is held in memory. `discovery.json` is an optional template.

Focused Vitest tests cover mapping, source discovery, message fragments,
completion order, corruption, precision, secret exclusion and output handling.
Focused lint, helper type checks and command builds pass. The existing sessions
registration test covers the added subcommand. ASR CI replays the patch and
compares and validates its synthetic sample. Qwen Code 0.26.5 completed isolated
synthetic message and read-tool runs through a OpenAI-compatible or Anthropic-compatible endpoint. The patched
command exported those recordings with zero validation errors or warnings.
Full upstream workspace release checks and an installed build of this pinned
source were not run.

## Verification scope

The live evidence above is from a prior revision. The current source has focused
regressions and package checks. Its full agent and model path has not been rerun.
