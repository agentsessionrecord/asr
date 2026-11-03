# Native ASR export for AstrBot

Export a saved session in an open format that search and code history tools can read. The export keeps the source facts available for later review.

This patch adds `sessions export` to AstrBot 4.29.3. It exports stored conversations as Agent Session Record. The producer method is `native`.

```sh
astrbot sessions export --format agent-session --session CONVERSATION_ID
astrbot sessions export --format agent-session --output ./exports
astrbot sessions export --format agent-session --database ./data/data_v4.db --output ./exports
```

Repeat `--session` to select several conversations. Without an output directory, exactly one explicit ID is required. Output filenames are SHA-256 digests of native IDs. Existing output files are refused. Missing conversations and unavailable databases fail with a nonzero exit code. The CLI banner is suppressed for session export so standard output holds only JSONL.

The patch applies to AstrBotDevs/AstrBot at `3d92821ad9d90df33fc242e7b159a3260075eb2c`. Apply the patch listed in `manifest.json` with `git am` in a writable checkout at that commit.

The exporter uses the native `ConversationV2` type and a read-only SQLite snapshot. It keeps saved message roles, exact text, tool-call IDs, names, raw argument strings and model-facing tool text. Raw JSON argument strings retain their exact integers and whitespace. Results with repeated call IDs occupy the final observation. Malformed message entries become positional gaps.

OpenAI-style saved tool history does not establish success or failure. Results use `status: unknown`. A user role does not establish a person's authorship. The current title and provider settings are not backdated into the session.

Known credential fields and recognized credential text are excluded. Media and opaque provider state are excluded. The exporter does not read provider credentials, fetch content, connect to a messaging platform or execute stored commands.

Known losses include model-call boundaries, usage, historical model identity, reasoning, event timestamps, approval and policy history, offered tools, complete instructions, file edits, commits, child sessions, copies and history removed from the saved conversation. A valid export does not establish that a saved conversation is complete.

Focused export and CLI regression tests pass. Ruff checks pass for the changed source. Pytest reports the project's existing fixture-loop-scope deprecation warning. The live test used AstrBot's real provider and conversation manager against a local OpenAI-compatible endpoint. The CLI exported three ASR records with zero validator errors and warnings. No messaging platform, dashboard or full tool-loop runner was exercised.

`samples/native/native.json` and `samples/asr/session.jsonl` are synthetic. The package check verifies source facts, patch syntax and integrity, privacy and ASR validation. The upstream tests are included in the patch. This patch does not add `--since`, discovery registration or a live ASR writer.

## Verification scope

The live evidence above is from a prior revision. The current source has focused
regressions and package checks. Its full agent and model path has not been rerun.
