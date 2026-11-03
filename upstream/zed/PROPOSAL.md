Human review required: upstream instructions require the README review banner. The human author must remove it after reviewing the source.

# Zed native export

Export a saved session in an open format that search and code history tools can read. The export keeps the source facts available for later review.

Applies to `zed-industries/zed` at `14b7b0ef3764d62a85070c8b5ccea105a2ad3235`.

The patch adds `DbThread::write_agent_session` in the agent crate. The example
reads a saved native `DbThread` JSON snapshot. Supply the database thread ID
separately because that ID is outside the snapshot type.

```bash
cargo run -p agent --example export_agent_session -- \
  --format agent-session SESSION_ID THREAD.json > session.jsonl
```

The export preserves retained text, reasoning, tool calls, structured JSON tool arguments and non-JSON argument
strings, tool results and native user message IDs. Mentions carry harness
provenance. Compaction summaries carry a gap for replaced history. Encrypted
reasoning has no opaque state or signatures. Incomplete calls become gaps.

Images, model identity, usage, approvals, settings, session relationships and
per-event timestamps are absent. Tool results follow their native map order.
The header declares the missing execution order and other losses. No human
identity or session end is inferred.

The focused agent test filter passed four tests, including three exporter
tests. The snapshot example and focused formatting check passed. Only the agent
crate was selected for compilation. A live GUI agent session was unavailable
in this headless environment. The patch adds neither a GUI export action nor
native database discovery. The README review marker is required by the
upstream contribution instructions and remains for human review.

To reproduce the packaged sample from an already patched checkout, run:

```bash
python3 upstream/zed/reproduce.py /path/to/patched/checkout
```

The reproduction uses temporary native fixture files, compares the exported
records with the packaged sample and runs the ASR validator. It does not start
inference. The package check runs in repository CI without fetching or compiling
the upstream project.
