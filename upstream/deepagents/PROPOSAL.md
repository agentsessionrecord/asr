# Native ASR export for Deep Agents Code

Export a saved session in an open format that search and code history tools can read. The export keeps the source facts available for later review.

This patch adds `threads export` to Deep Agents Code 0.2.2. It exports native SQLite message writes as Agent Session Record. The producer method is `native`.

```sh
dcode threads export --format agent-session --session THREAD_ID
dcode threads export --format agent-session --session THREAD_ID --output ./exports
dcode threads export --format agent-session --output ./exports
```

One explicit session without `--output` writes JSONL to standard output. An output directory receives one file per selected thread. Filenames are SHA-256 digests of native IDs. Existing output files are refused. Source reads use a consistent read-only SQLite transaction. Missing threads fail with a nonzero exit code. The command does not start the model or the agent server.

The patch applies to langchain-ai/deepagents at `e9f0d8855cff6d7e79d87afc15c2defc62214a71`. Apply the patch listed in `manifest.json` with `git am` in a writable checkout at that commit.

Native LangChain message types provide roles, exact text, tool names, effective JSON arguments and explicit tool outcomes. The exporter reads root-namespace message deltas in the same checkpoint, task and write order that the project uses for native history replay. It retains work removed from later context. Message revisions and result updates occupy their last observation. Removal markers do not erase captured work. Corrupt writes become gaps. Valid message IDs stay native. Other record IDs are deterministic and avoid collisions. Missing native call IDs get deterministic IDs and a declared loss.

Known credential fields and recognized credential text are excluded. Large native argument integers become exact decimal strings. Unsupported media and opaque provider state are excluded. The serializer disables pickle fallback. No attachment, current instruction file or current repository state is read for export.

Saved message boundaries alone do not prove model-call boundaries. The export declares missing usage, model identity, reasoning coverage, inference settings, policy and approval history, complete instructions, tool definitions, native timestamps, file edits, commits, child sessions and copy detection. It does not treat a message's user role as human authorship or the end of a file as a session end. Offloaded history and nested checkpoint namespaces are not recovered.

Focused export and argument tests pass. Ruff and type checks pass for the changed exporter and its tests. The live test used the Code model factory and Deep Agents SDK 0.7.32 graph with native SQLite checkpoint persistence against a local OpenAI-compatible endpoint. The real CLI exported three ASR records with zero validator errors and warnings. The interactive TUI and full headless Code server were not run.

`samples/native/native.json` contains synthetic LangChain message serialization. `samples/asr/session.jsonl` is its export. The package check verifies source facts, patch syntax and integrity, privacy and ASR validation. The upstream tests are included in the patch. This patch does not add `--since`, discovery registration or a live ASR writer.

## Verification scope

The live evidence above is from a prior revision. The current source has focused
regressions and package checks. Its full agent and model path has not been rerun.
