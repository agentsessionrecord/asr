# Kilo Code native ASR export

Export a saved session in an open format that search and code history tools can read. The export keeps the source facts available for later review.

This patch adds a native session export command to the Kilo Code CLI.
It applies to `Kilo-Org/kilocode` commit `0a9faeff69fff8712da184ee5188bb7985c6f057`.
The local implementation commit is `2f432a05f4260a0357259dc025722a656b55e3bb`.
This source repository is distinct from `Kilo-Org/kilo`.

```sh
kilo sessions export --format agent-session --session SESSION_ID
kilo sessions export --format agent-session --session SESSION_ID --output new-directory
kilo sessions export --format agent-session --since 2026-01-01T00:00:00Z --output new-directory
```

Repeat `--session` to select several sessions, or omit it with `--output` to select
all sessions. Standard output requires exactly one selected session.
`--since` selects sessions changed since that time.
`--database` selects a native database without changing the default installation.
`--write-discovery` creates an opt-in discovery file.
The command refuses to replace output directories or discovery files.

The exporter reads retained V1 sync events in native sequence order inside a
read-only SQLite transaction. It bypasses interactive startup, migrations and
telemetry. The two shared entrypoint lines use Kilo's change markers.

It records messages, reasoning, model tool calls, terminal results, effective
rewritten inputs, requested models, call usage, costs and recorded mode and
permission changes. Null settings updates clear earlier facts.
An explicit winning allow or deny rule becomes a policy approval immediately
before its result. This snapshot has no invented decision timestamp.
Success alone never establishes approval. Manual approval history stays unknown.
Input totals include cache reads and writes. Output totals include reasoning.
Unsafe core counts are omitted and kept exactly as strings in vendor data.

V2 session history and missing creation history fail explicitly.
Corrupt and unmapped native events produce gaps.
Complete settings and approval history, offered tools, media, content revisions,
normalized file changes, commits, copy detection and subagent links remain incomplete.
An ambiguous native parent ID stays in vendor data.
The exporter leaves served models, cost provenance and session end times unknown.
Known credentials and provider replay state are excluded.

Six focused upstream tests and the CLI package type check pass.
The shared-file annotation check passes. Focused lint has zero errors and ten
warnings, including one existing startup warning and boundary assertions and
asynchronous test matcher warnings.
A real isolated session completed through a local OpenAI-compatible endpoint.
Its native export had 10 records and passed the reference validator with zero
errors and warnings. The committed source and output samples are synthetic.

`node --test upstream/opencode/check.test.mjs` checks this patch bundle and its
synthetic output. The native tests are in the patch and run from
`packages/opencode` with `bun test test/kilocode/agent-session.test.ts`.

## Verification scope

The live evidence above is from a prior revision. The current source has focused
regressions and package checks. Its full agent and model path has not been rerun.
