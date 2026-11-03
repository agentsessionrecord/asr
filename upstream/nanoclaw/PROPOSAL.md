# NanoClaw native mailbox export

Export a saved session in an open format that search and code history tools can read. The export keeps the source facts available for later review.

Applies to `qwibitai/nanoclaw` at `acc2b1c8f52a954368cfaf04b61c32f9a1efc280`.

The patch adds an optional skill utility without changing the host or container.
Run it in a patched checkout with its pinned dependencies installed.

```bash
pnpm exec tsx .claude/skills/export-agent-session/scripts/export-agent-session.ts \
  --session ID --directory data/v2-sessions/GROUP/ID \
  --format agent-session > session.jsonl
```

The utility reads native inbound and outbound SQLite mailboxes in read-only
mode. It preserves text, unique native record IDs and exact native sequence
order. Invalid timestamps are omitted. Unsupported payloads become gaps.
Scheduled inbound tasks keep their origin. A recorded sender session becomes a
`from` reference. It does not establish a copied-history relationship.

The export covers mailbox traffic. Internal model calls, reasoning, tools,
approvals, settings, identities and usage are absent and listed in the header.
It does not infer that inbound text came from a human or that outbound text
came from a model. Stop the session for a stable snapshot across both files.

The focused Vitest contract, TypeScript project check, ESLint check, skill
structure check and native mailbox CLI export passed. The contract covers
native order against reversed timestamps, excluded credential fields, missing
sequence, invalid dates and session identity. No live host or agent container
was configured. The included sample uses synthetic mailboxes.

To reproduce the packaged sample from an already patched checkout, run:

```bash
python3 upstream/nanoclaw/reproduce.py /path/to/patched/checkout
```

The reproduction uses temporary native fixture files, compares the exported
records with the packaged sample and runs the ASR validator. It does not start
inference. The package check runs in repository CI without fetching or compiling
the upstream project.
