# Agent Session Record export for Warp

This patch adds an ASR export example to the persistence crate of [Warp](https://github.com/warpdotdev/warp) for saved conversations. The pinned base is `3dca8f995cc116814f17fc818ee0c37ec1141eaa`. [Apply the patches](../README.md#apply-a-patch) in a clean checkout at that base. The [proposal](PROPOSAL.md) gives runtime requirements, build steps and output options.

```sh
cargo run -p persistence --example export_agent_session -- \
  --format agent-session DATABASE CONVERSATION_ID > session.jsonl
```

One task in a native SQLite conversation supplies IDs, timestamps, the initial absolute working directory, user and assistant text and retained reasoning. Opaque provider state is left out. The export applies Warp's configured redaction rules and built-in patterns to text and reasoning. Changed records carry truncation markers and the header declares the loss. A match in the identity or working directory stops the export before any bytes are written. Tools, context attachments, settings, approvals, models, usage and relationships are outside this text export. There is no UI action or discovery manifest, and no human authorship or end time is inferred.

## Checks

```sh
node upstream/warp/check.mjs
node upstream/warp/reproduce.mjs /path/to/upstream-checkout
```

See [package checks](../README.md#check-a-package). Three export tests, the type check, Clippy, format and the native fixture pass, and [refresh.json](refresh.json) has the results. No live model run covers this revision.
