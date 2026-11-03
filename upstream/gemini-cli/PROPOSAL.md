# Native ASR export for Gemini CLI

Export a saved session in an open format that search and code history tools can read. The export keeps the source facts available for later review.

This patch adds `gemini sessions export --format agent-session`. It exports saved
native recordings without a model call or account lookup.

It applies to upstream commit
`a60946692b11e2f144a8fe4db46bbc4e514daa7a` from
<https://github.com/google-gemini/gemini-cli>.

```sh
git am patches/0001-native-agent-session-export.patch
gemini sessions export --format agent-session --session SESSION_ID
gemini sessions export --format agent-session --input transcript.jsonl --session SESSION_ID
gemini sessions export --format agent-session --output exports
```

A single selected session writes JSONL to standard output. Directory output
supports repeated selectors and uses private hashed filenames. Existing files
are refused. `--since` selects by the native file modification time. The normal
command discovers top-level current-project recordings and prefers migrated
JSONL over its JSON sibling. Explicit input bypasses global configuration.

The exporter preserves exact recorded text, tool arguments, model-facing result
parts and native IDs. Unknown native content uses vendor content parts. Updated messages and results appear at the position of their final saved version. Intervening records and retained
rewound work keep their positions. Invalid lines and incomplete tails become
gaps. Known secrets and opaque provider state are excluded. Native large
integers remain exact strings.

The native recordings do not supply complete approval or settings history.
The patch declares those losses. It also declares omitted model-call accounting,
file-change normalization, commits, tool definitions, complete instructions,
copy detection and lineage. It does not infer approvals, model calls, human
authorship, exit codes or historical repository state. Several recording segments
with the same identity require explicit source selection. Full input is held in
memory. This patch does not add live ASR or automatic discovery registration.
`discovery.json` is an optional source registration template.

Focused Vitest tests cover native mapping, completion order, source discovery,
corruption, exact text, integer precision, secrets and private output files.
Focused lint, helper type checks and command builds pass. The patch is replayed
in ASR CI and its synthetic output is compared byte for byte and validated.
Gemini CLI 0.66.0 completed isolated synthetic message and read-tool runs through
a OpenAI-compatible or Anthropic-compatible endpoint. The patched command exported those native recordings with
zero validation errors or warnings. Full upstream workspace release checks and
an installed build of this pinned source were not run.

## Verification scope

The live evidence above is from a prior revision. The current source has focused
regressions and package checks. Its full agent and model path has not been rerun.
