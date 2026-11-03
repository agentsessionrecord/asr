# Agent Session Record export for AstrBot

Export a saved session as Agent Session Record so local tools can search and review its recorded work.

This adds `astrbot sessions export --format agent-session` to AstrBot 4.29.4. It reads stored `ConversationV2` histories through a read-only SQLite snapshot. Repeat `--session` to select conversations. Without an output directory, exactly one explicit ID is required. Output filenames are SHA-256 digests of native IDs. Existing output files are refused.

Saved roles, exact text, tool-call IDs, names, raw argument strings and model-facing tool text are preserved. Raw argument strings keep their original integer precision and whitespace. Repeated result IDs occupy their final observation. Malformed entries become positional gaps. The session export command emits JSONL without the CLI banner.

The existing tracing and bounded-history work does not make the saved conversation a complete event log. This patch exports the saved conversation and declares missing history. Tool outcomes, inference boundaries, usage, historical models, timestamps, approvals, file edits, commits and session relationships remain incomplete. Provider settings and messaging platforms are not opened.

```sh
astrbot sessions export --format agent-session --session CONVERSATION_ID
astrbot sessions export --format agent-session --output exports
```

Source: [AstrBotDevs/AstrBot](https://github.com/AstrBotDevs/AstrBot), base `f926af99ec5f8bd85b64413f8bfad55da76ef73b`. Apply the ordered patches in [manifest.json](manifest.json) with `git am` in a clean checkout at that base.

Output uses ASR 0.1 with `producer.method: native`. Known credential fields or recognized secret text are excluded where the source mapping supports them. Review exports before sharing. Filtering cannot identify every secret.

The native fixture and ASR sample are synthetic. [TEST-RESULTS.md](TEST-RESULTS.md) states the current verification results and remaining limits. Structural validation does not prove complete capture.
