# Native Agent Session Record export

Export saved Gemini CLI sessions for tools that need an open, ordered record.

For [Gemini CLI](https://github.com/google-gemini/gemini-cli):

```sh
gemini sessions export --format agent-session --session SESSION_ID
```

Adds an offline `sessions export` subcommand. Updated messages and results
occupy their final saved position. Unknown content parts stay in namespaced
metadata.

The exporter writes ASR 0.1 from saved native JSONL recordings. It preserves
retained text, reasoning and tool results, declares missing facts and filters
known credentials. Review exports before sharing them.

Approvals, settings, model accounting, edits, commits, tool definitions,
instructions and lineage remain incomplete. Multiple recording segments need
explicit selection. Input is held in memory.

The workspace build, 11 focused export tests, CLI type check and focused ESLint
pass. Validation used npm 11, which supports the repository's dependency alias
overrides. Synthetic native fixture exports pass the ASR validator with zero
errors and zero warnings. Tests cover mapping, ordering, corrupt input,
credential filtering and output selection.
