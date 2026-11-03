# Agent Session Record from ForgeCode conversation dumps

Export retained conversation context for inspection and indexing across agents.
The patch extends the existing `dump` command with a format selector.
The default JSON dump and `--html` option keep their current behavior.

```sh
forge conversation dump ID --format agent-session > session.jsonl
```

`--format agent-session` conflicts with `--html`. It writes JSON Lines to standard
output. The domain example also reads the existing JSON dump wrapper.

```sh
cargo run -p forge_domain --example export_agent_session -- \
  CONVERSATION.json > session.jsonl
```

The output retains conversation identity, source start time, text, reasoning
summaries, tool argument strings, call IDs and results. An initial gap declares
that only retained context is available. Opaque state, signatures and image bytes
are excluded. Duplicate result IDs fail before output. Generated call IDs cannot
pair with unrelated native results.

Models, usage, approvals, settings, session relationships and per-message times
are absent. No original interleaving, human authorship or session end is inferred.
Output is ASR 0.1.

Source: <https://github.com/tailcallhq/forgecode> at `a22b49288856d5b3f3ca57e8532683d54a662c8c`.

Focused verification commands:

```sh
cargo test -p forge_domain agent_session --lib
cargo test -p forge_main test_conversation_dump --bin forge
cargo check -p forge_main
cargo clippy -p forge_domain -p forge_main --all-targets -- -D warnings
cargo fmt -p forge_domain -p forge_main --check
```

Current results and limitations are recorded in [refresh.json](refresh.json).
The fixtures are synthetic. No current live inference test is claimed.
