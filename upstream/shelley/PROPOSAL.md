# Shelley native export

Export a saved session in an open format that search and code history tools can read. The export keeps the source facts available for later review.

Applies to `boldsoftware/shelley` at `e8dd9cc6817248188d2be2912680e8555ef72f13`.

The patch adds `DB.WriteAgentSession` and a small database export command.

```bash
go run ./cmd/shelley-export --db DATABASE --session ID \
  --format agent-session > session.jsonl
```

The command opens an existing native WAL database in read-only mode. It uses
native conversation and message queries. Text, retained reasoning, supported
images, raw tool input, tool IDs, results and timestamps follow native sequence
order. Repeated result updates fold into the last result at its completion
position. Unique native message IDs survive on each row's first exported part.
Human authorship is set only when a native user email is recorded.

Opaque reasoning state and signatures are excluded. Unsupported rows or content
become gaps. Model identity, usage, approvals, settings, native events and session
relationships are not exported. The header lists these losses. No end time is
inferred. Stop active writers when a stable database snapshot is needed.

Two focused database tests, vet, a command build and a synthetic SQL export
passed. A real native loop completed one synthetic turn through a local model
endpoint using private native provider settings. Its native database export passed
validation. That test exercised the native loop and database, without the web UI.
The included live sample contains only that synthetic exchange.

To reproduce the packaged sample from an already patched checkout, run:

```bash
python3 upstream/shelley/reproduce.py /path/to/patched/checkout
```

The reproduction uses temporary native fixture files, compares the exported
records with the packaged sample and runs the ASR validator. It does not start
inference. The package check runs in repository CI without fetching or compiling
the upstream project.

## Verification scope

The live evidence above is from a prior revision. The current source has focused
regressions and package checks. Its full agent and model path has not been rerun.
