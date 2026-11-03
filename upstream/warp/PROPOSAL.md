# Saved Warp conversations as Agent Session Record

Export retained conversation text for local inspection and indexing.
The reference patch adds `AgentConversation::write_agent_session` to persistence.
It reads an existing SQLite database without changing it.

```sh
cargo run -p persistence --example export_agent_session -- \
  --format agent-session DATABASE CONVERSATION_ID > session.jsonl
```

Exactly one task is supported. The export retains conversation and message IDs,
source times, an initial absolute working directory, text and recorded reasoning.
Unsupported messages become gaps. Invalid times fail before output.
Tools, models, usage, approvals, attachments, settings and session relationships
are outside this text projection. No session end or human authorship is inferred.
Configured upstream secret-redaction rules and built-in redaction patterns filter
text and reasoning. Matching identities and cwd refuse export before output.
Redaction declares loss and marks changed records. Pattern coverage does not
discover arbitrary secret answers.
Output is ASR 0.1. No UI action or discovery manifest is added.

Warp's client is open source. Persistence code is covered by the repository's
AGPL licence. The MIT UI crates do not change that scope.
The package includes a short product and technical spec draft for
[observability hooks #7834](https://github.com/warpdotdev/warp/issues/7834)
in [specs/GH7834](specs/GH7834/product.md). The issue is ready to spec.
The reference text exporter implements only a small part of that draft.
Spec acceptance and implementation readiness are separate from local checks.

Source: <https://github.com/warpdotdev/warp> at `3dca8f995cc116814f17fc818ee0c37ec1141eaa`.

Focused verification commands:

```sh
cargo test -p persistence agent_session --lib
cargo clippy -p persistence --all-targets --tests -- -D warnings
cargo fmt -p persistence --check
```

Current results and limitations are recorded in [refresh.json](refresh.json).
The fixtures are synthetic. No current live inference test is claimed.
