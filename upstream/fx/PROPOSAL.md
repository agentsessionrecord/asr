# fx native export

Export a saved session in an open format that search and code history tools can read. The export keeps the source facts available for later review.

Applies to `vercel-labs/fx` at `e10e517357560f050f408723165326867e1ef932`. Requires Zig 0.17.0.

The patch adds a native sessions export command.

```bash
fx sessions export --format agent-session --session ID > session.jsonl
```

The export reads durable session state through the native session adapter. It
records retained user and assistant text, runtime context, tool steps, raw tool
arguments, results, steering boundaries and interrupted assistant text.
Compaction summaries have a gap for removed history. Sidecar output and image
omissions mark results as truncated. An active interrupted call outside the
retained steps becomes a gap. Duplicate result IDs reject the buffered export.

Provider replay state, recovery checkpoints, images, model identity, usage,
approvals, settings and timestamps are excluded. The header lists these losses.
No human authorship or end time is inferred.

Two focused Zig tests and a debug build passed. The freshly built binary
exported the upstream synthetic session fixture at
`tests/fixtures/v1-sessions/plain/sessions/cb1PK0RGxCmY`.
The fixture is copied here, with its native event file named `events.native`.
It is renamed to `events.jsonl` only inside the temporary reproduction directory.
A live inference test was skipped because native provider auth accepts an
environment variable name rather than a private key file. The required
file-only provider key rule could not be met without an unrelated auth change.

To reproduce the packaged sample from an already patched checkout, run:

```bash
python3 upstream/fx/reproduce.py /path/to/patched/checkout
```

The reproduction uses temporary native fixture files, compares the exported
records with the packaged sample and runs the ASR validator. It does not start
inference. The package check runs in repository CI without fetching or compiling
the upstream project.
