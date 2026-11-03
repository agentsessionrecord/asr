# Xum native ASR export

Export a selected Xum chat segment as ASR for review outside Xum. The command
uses Xum's current CLI and validates native `MuxMessage` records with its schema.
It does not load providers or application configuration.

`xum sessions export --session ID --source chat.jsonl --format agent-session`
keeps text, reasoning and final tool call and result snapshots. It folds message
replacements by native ID and history sequence. UI tool output is namespaced
metadata, with unknown execution status. Known credential fields are excluded.
Output files must be new and use mode 600.

A prefix gap states that this is one segment. Xum's full history is
`chat-archive.jsonl` followed by `chat.jsonl`. Archives, partial files and legacy
root discovery are outside this command. It does not infer model calls from UI
messages or reconstruct usage, approvals, settings or tool definitions.

Run the focused Bun tests, `make build-main`, `make typecheck`, and targeted
Oxlint and Prettier checks. Tests cover snapshot replacement, tool pairing,
credential filtering and corrupt input. The fixture uses only synthetic content.

Source: [https://github.com/coder/xum](https://github.com/coder/xum).
Base: `7a11fb8cba1afb39f74d268029d449e2d1de9156`.
