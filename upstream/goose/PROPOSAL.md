# Agent Session Record export for goose

Export saved sessions for inspection and tools that read several agents' records.
Add Agent Session Record (ASR) to the existing session export format selector.
The exporter lives beside the Markdown and HTML exporters in `session`.
It reads stored history in insertion order, including inactive context.

```sh
goose session export --format agent-session --session-id SESSION_ID
goose session export --format agent-session --session-id SESSION_ID --output exports
```

The first command writes JSON Lines to standard output. The second writes one
file in the selected directory. Only one explicitly selected session is supported.
The existing command and identifier spellings are used.

Text, content order, calls, model-facing results, reasoning and explicit
confirmation responses survive. Folded results occupy their final stored position.
A persistent installation namespace distinguishes repeating native session IDs.
A final settings snapshot does not establish settings for earlier events.
Missing models, inference boundaries, usage, edit evidence, commits, copied
history and subagent links are declared. No session end is inferred.

This implements export only. The existing `session/import_formats` readers for
Claude Code, Codex and Pi remain the import path. An ASR reader there is separate
work. The trace import and export roadmap does not establish replay support.
Output is ASR 0.1. Secret answers and known credential patterns are excluded.

Source: <https://github.com/aaif-goose/goose> at `0aa212e61d43e35ee2875ca5aa23c28ebac882c7`.

Focused verification commands:

```sh
cargo test -p goose --test agent_session_export
cargo check -p goose-cli
cargo clippy -p goose -p goose-cli --all-targets -- -D warnings
cargo fmt -p goose -p goose-cli --check
```

Current results and limitations are recorded in [refresh.json](refresh.json).
The fixtures are synthetic. [refresh.json](refresh.json) also records a live
session exported by the patched CLI.
