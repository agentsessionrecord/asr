# NanoClaw ASR utility skill

Source: [https://github.com/nanocoai/nanoclaw](https://github.com/nanocoai/nanoclaw).
Pinned base: `f7440e85f8b2a75b17fc9a08f0cc6aacf723a1e2`.

The patch adds only `.claude/skills/export-agent-session/`. It installs no core
code or configuration. Select a NanoClaw session and verify which Claude provider
continuation belongs to it. Select that continuation's SDK JSONL file explicitly.

```sh
pnpm exec tsx .claude/skills/export-agent-session/scripts/export-agent-session.ts \
  --session SESSION_ID --transcript SELECTED_TRANSCRIPT.jsonl \
  --format agent-session > session.asr.jsonl
```

The skill exports retained text, tool calls and results, provider response IDs,
served models, reasoning summaries and inclusive token counts. Split response
blocks share one inference. Later usage snapshots replace counts rather than
being added together. Known credentials and signatures are excluded.

This profile covers one Claude continuation. It does not merge mailbox delivery
or other continuations and does not read raw SQL. Other providers need separate
native mappings. Missing approvals, settings, edits, commits and lineage are
declared. Unsupported records and corrupt lines become gaps.

Native fixture reproduction:

```sh
node upstream/nanoclaw/reproduce-native.mjs /path/to/patched-checkout
```

## Package checks

The manifest pins the source base, patch commits and file digests. Apply the
ordered patches in a clean checkout at that base with `git am patches/*.patch`.
The package is not installed by the ASR CLI.

From the ASR repository root, run:

```sh
node upstream/nanoclaw/check.mjs
node upstream/nanoclaw/reproduce.mjs /path/to/patched-checkout
```

The second command checks replay in a temporary Git index. It preserves the
checkout and requires the pinned commits. It does not build the agent.
Native fixture reproduction is a separate check described below.

The root build and focused formatting, lint, TypeScript and unit checks pass.
The native synthetic continuation export matches the packaged sample and passes
the reference validator with zero errors and warnings.
See [verification.json](verification.json) for the current status. Existing
live evidence is historical and does not validate this revision. No live model
request was made for this refresh.

Keep exports private and review them before sharing. Pattern filters cannot
identify every secret. Valid ASR does not establish complete capture.
