# Mux native Agent Session Record export

Export a saved session in an open format that search and code history tools can read. The export keeps the source facts available for later review.

Adds an explicit offline export command to the current Xum CLI. The ASR agent name remains `mux` for the native format registry.

Applies to [https://github.com/coder/mux](https://github.com/coder/mux) at `f10bd913c839ee09a4af3a0cf5e36c159ff17c9b`. The local patch commit is `3e7534eeed9dca589b735c10061b9e14e8392310`.

Apply the patch with `git am patches/0001-native-agent-session-export.patch` in a clean checkout of that base.

```text
xum sessions export --session SESSION_ID --source chat.jsonl --format agent-session --output session.asr.jsonl
```

It validates native rows with MuxMessageSchema and records text, readable reasoning, final tool-call snapshots and final result snapshots. Full message replacements use native ID and history sequence. Corrupt rows and incomplete tails produce gaps. Native IDs are retained when usable.

The selected file is a segment. The exporter declares a prefix gap and does not claim to reconstruct archives or partial files. It omits provider state, usage aggregates, approvals, settings and tool definitions. Tool-specific UI output does not establish execution success, so result status stays unknown. Snapshot revisions that are replaced are not credited twice.

Supported source: the native MuxMessage schema for one chat.jsonl segment at this revision. Output uses ASR `0.1` and `producer.method: "native"`. File output is exclusive and private where the command writes a file.

Checks: 3 focused Bun tests. Main TypeScript project typecheck. Oxlint and Prettier. The included native fixture and sample are synthetic. The sample passes the reference validator with zero errors.

An isolated source CLI run against a local OpenAI-compatible endpoint exported 10 records with zero errors or warnings. This run covered text and segment handling. Tool snapshots are covered by synthetic tests. The source exporter was then refined for native IDs and replacement snapshots and rechecked on the synthetic fixture.

`manifest.json` pins the upstream base, local commit and packaged file hashes. Run `node upstream/mux/check.mjs` from the ASR repository to check this patch package without upstream dependencies.

## Verification scope

The live evidence above is from a prior revision. The current source has focused
regressions and package checks. Its full agent and model path has not been rerun.
