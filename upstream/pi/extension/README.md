# ASR export extension

Export a saved Pi session as Agent Session Record JSON Lines for local search or collection.
The exporter includes every retained branch in native file order.

From this directory, install the extension with `pi install .`.
Restart Pi and run `/export-asr output.jsonl` to export the current saved session.
The output path is relative to the current workspace. Existing files are refused.

For offline export with Node 22.19 or later:

```sh
node cli.ts --session native-session.jsonl --format agent-session --output session.jsonl
```

The exporter keeps recorded response IDs, model identities, inclusive usage,
text, reasoning summaries and tool calls. It excludes provider signatures and
opaque state. The header declares missing approvals, offered tools, edits,
commits, lineage and other unsupported evidence. Review content before sharing it.
