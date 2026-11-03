# Saved Zed threads as Agent Session Record

Export retained thread content so tools can inspect it without opening the editor.
The patch adds `DbThread::write_agent_session` and a snapshot example.

```sh
cargo run -p agent --example export_agent_session -- \
  --format agent-session SESSION_ID THREAD.json > session.jsonl
```

Supply the native database thread ID separately from its saved JSON snapshot.
The export retains text, reasoning summaries, native call IDs, JSON or text
arguments and recorded tool outcomes. Compaction summaries have gaps for replaced
history. Opaque reasoning state and signatures are excluded.

Tool result statuses follow ACP terminal outcomes. Delta's
`thread append` reads JSON Lines with `schemaVersion`, `sequence`, optional
`turnSequence` and an ACP v2 `update`. ASR is a separate durable record format.
This snapshot exporter neither reads nor produces Delta envelopes. An ACP bridge
must fold updates in sequence order at completion and retain native tool IDs.
See the [ACP mapping](../../guides/acp.md).

Models, usage, approvals, settings, relationships and per-event timestamps are
missing. Tool results follow their native map order, which does not establish
execution order. No human authorship or session end is inferred.
There is no GUI action or database discovery. Output is ASR 0.1.

Source: <https://github.com/zed-industries/zed> at `57dfd54adebb6d4a62cd1c42d397acb667a71c0a`.

Focused verification commands:

```sh
cargo test -p agent agent_session --lib
cargo clippy -p agent --all-targets -- -D warnings
cargo fmt -p agent --check
```

Current results and limitations are recorded in [refresh.json](refresh.json).
The fixtures are synthetic. No current live inference test is claimed.
