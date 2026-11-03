# NanoClaw ASR utility skill

Export a selected NanoClaw Claude continuation as ASR, including tool and model
calls. The change is a utility skill under `.claude/skills/`. It changes no core
module, database, provider or installed configuration.

The operator selects the NanoClaw session and confirms its provider continuation.
The skill reads that continuation's SDK transcript in file order. It preserves
text, tool pairing, response IDs, served models and inclusive input counts.
Multiple SDK rows for one response share one inference with final usage snapshots.
Unsafe counts are retained exactly in metadata and omitted from core numeric fields.

This export does not join mailbox traffic into guessed chronology. It covers one
Claude continuation. Other providers, mailbox delivery, approvals, edits, commits
and child lineage remain explicit losses. Known credential fields and provider
signatures are excluded. The utility leaves nothing installed when it finishes.

Run the skill's focused Vitest tests, targeted TypeScript check and Prettier check.
The synthetic fixture includes a split response, reasoning, a tool call and result,
zero usage and descending timestamps. Tests cover unsafe counts and corrupt input.

Source: [https://github.com/nanocoai/nanoclaw](https://github.com/nanocoai/nanoclaw).
Base: `f7440e85f8b2a75b17fc9a08f0cc6aacf723a1e2`.
