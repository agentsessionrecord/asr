# Shelley session export

Export a conversation from `shelley.db` as Agent Session Record for search and session review.

The patch adds a small standalone database export command and `DB.WriteAgentSession`. It opens an existing `shelley.db` in read-only mode. It changes neither the database schema nor saved messages.

```sh
go run ./cmd/shelley-export --db /path/to/shelley.db \
  --session SESSION_ID --format agent-session > session.asr.jsonl
```

Native sequence order supplies text, retained reasoning, supported inline images, tool arguments, IDs, final results, and timestamps. Repeated tool results fold into the last result at its completion position. Human authorship is supplied only when the native row records a user email. Opaque reasoning and provider metadata are excluded. Unsupported content becomes a gap. Models, usage, approvals, settings, file changes, commits, and relationships are declared missing. The export is not a redactor. Review conversation content before sharing.

The patch targets [shelley](https://github.com/boldsoftware/shelley) at `3df54607e37a808362437f96f17d1d276b74684a`. Tests cover exact text, source order, final tool results, and excluded provider state. [TESTS.json](TESTS.json) states which checks ran on this revision.
