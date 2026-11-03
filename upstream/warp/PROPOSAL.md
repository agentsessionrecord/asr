# Warp native export

Export a saved session in an open format that search and code history tools can read. The export keeps the source facts available for later review.

Applies to `warpdotdev/warp` at `89de3f5c9945eeee277e713f111d707d39857dff`.

The patch adds `AgentConversation::write_agent_session` in the persistence crate.
A small command reads a native SQLite database without changing it.

```bash
cargo run -p persistence --example export_agent_session -- \
  --format agent-session DATABASE CONVERSATION_ID > session.jsonl
```

The export accepts exactly one task in a conversation. It preserves the native
conversation ID, unique message IDs, source timestamps, initial absolute working
directory, user text, assistant text and retained reasoning. Unsupported messages
become gaps in their source positions. It rejects invalid timestamps before writing.

Tool calls, results, context attachments, settings, approvals, model identity,
usage and session relationships are outside this text export. The header lists
these losses. It does not infer human authorship or an end time.

Two persistence unit tests, crate lint and the SQLite example passed. Only the
persistence crate was selected for compilation. The synthetic SQLite source in
`samples/native/source.sql` produced the included sample. The app needs an account for
a live agent session, so this patch has no live inference test. No UI action or
discovery manifest is added.

To reproduce the packaged sample from an already patched checkout, run:

```bash
python3 upstream/warp/reproduce.py /path/to/patched/checkout
```

The reproduction uses temporary native fixture files, compares the exported
records with the packaged sample and runs the ASR validator. It does not start
inference. The package check runs in repository CI without fetching or compiling
the upstream project.
