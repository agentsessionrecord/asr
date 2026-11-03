# OpenCode native ASR export

Export a saved session in an open format that search and code history tools can read.
Sessions must be recorded with `OPENCODE_AGENT_SESSION_HISTORY=1` enabled before
recording begins. Restart an existing server with that setting.

This patch adds Agent Session Record output to the existing session export command.
It applies to `anomalyco/opencode` commit `bf5d12c588911a35ec56ad991c3b83cf937f424a`.
The local implementation commit is `840e70fb11bfc85a76a587f8d3f47f47d582c970`.

```sh
OPENCODE_AGENT_SESSION_HISTORY=1 opencode serve
opencode session export SESSION_ID --format agent-session
opencode session export SESSION_ID --format agent-session --output new-directory
```

The existing positional session argument and JSON format still work.
This patch selects one session at a time. It does not offer bulk export or `--since`.
`--output` requires a new directory and uses a hashed filename.
Add `--write-discovery` to create an opt-in discovery file.
The command refuses to replace an existing output directory or discovery file.

The exporter uses OpenCode's typed durable event API.
It keeps messages, reasoning, model tool calls and results in their recorded order,
requested models, call usage, native costs and recorded mode and permission changes.
Input totals include cache reads and writes. Output totals include reasoning.
It leaves the served model and cost provenance unknown.
It does not turn idle time or the last reply into a session end.

History capture is optional in the upstream agent, so older sessions may have no
exportable history. Missing creation history fails explicitly.
Fork history also fails because copied records need a separate mapping.
Shell history and content revisions produce gaps.
Approval history, complete settings, offered tool lists, normalized file changes,
commits, media, copy detection and subagent tool links remain incomplete.
Other internal events have no normalized mapping and are declared as a loss.
Known credentials are excluded and changed records carry truncation markers.
Provider replay state is excluded. Unsafe native integers already parsed by the
client cause an error. Inclusive count overflow keeps exact strings in vendor data.

Eleven focused upstream tests pass, including five existing import and export tests
and a CLI help regression for session selection.
The CLI package type check and focused lint pass.
A real isolated session completed through a local OpenAI-compatible endpoint.
Its native export had 8 records and passed the reference validator with zero errors
and warnings. The committed source and output samples are synthetic.

`node upstream/opencode/check.mjs` checks the patch bundle, synthetic
source facts, output order and reference validation. The upstream tests are included
in the patch and run from `packages/cli` with
`bun test --timeout 30000 test/agent-session.test.ts test/import-export.test.ts`.

## Verification scope

The live evidence above is from a prior revision. The current source has focused
regressions and package checks. Its full agent and model path has not been rerun.

Would durable history be appropriate as a default, or would an export of stored
rows fit better with the project? Stored rows cannot recover missing event history.
