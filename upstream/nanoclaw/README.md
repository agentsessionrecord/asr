# Agent Session Record export skill for NanoClaw

This patch adds an ASR export skill to [NanoClaw](https://github.com/nanocoai/nanoclaw). It touches only `.claude/skills/export-agent-session/` and installs no core code or configuration. The pinned base is `f7440e85f8b2a75b17fc9a08f0cc6aacf723a1e2`. [Apply the patch](../README.md#apply-a-patch) in a clean checkout at that base.

Select a NanoClaw session, confirm which Claude provider continuation belongs to it, then pass that continuation's SDK JSONL file:

```sh
pnpm exec tsx .claude/skills/export-agent-session/scripts/export-agent-session.ts \
  --session SESSION_ID --transcript SELECTED_TRANSCRIPT.jsonl \
  --format agent-session > session.asr.jsonl
```

The skill exports retained text, tool calls and results, provider response IDs, served models, reasoning summaries and inclusive token counts. Split response blocks share one inference, and a later usage snapshot replaces earlier counts instead of adding to them. Known credentials and signatures are left out. The export covers one Claude continuation. It does not merge mailbox delivery or other continuations, read raw SQL or map other providers. Missing approvals, settings, edits, commits and lineage are declared, and unsupported records and corrupt lines become gaps.

## Checks

```sh
node upstream/nanoclaw/check.mjs
node upstream/nanoclaw/reproduce.mjs /path/to/patched-checkout
node upstream/nanoclaw/reproduce-native.mjs /path/to/patched-checkout
```

See [package checks](../README.md#check-a-package). The third command reproduces the native fixture. The root build and focused formatting, lint, TypeScript and unit checks pass. The synthetic continuation export matches the packaged sample and validates with no errors or warnings. [verification.json](verification.json) has the current status. No live model run covers this revision.
