# ForgeCode native export

Export a saved session in an open format that search and code history tools can read. The export keeps the source facts available for later review.

Applies to `antinomyhq/forge` at `7639d2b18418bd1948609ffd4e46f4acca30a117`.

The patch adds `Conversation::write_agent_session` and a CLI export command.

```bash
forge conversation export ID --format agent-session > session.jsonl
```

A domain example also accepts a saved Conversation JSON object or its native
dump wrapper.

```bash
cargo run -p forge_domain --example export_agent_session -- \
  CONVERSATION.json > session.jsonl
```

The export records retained context, native conversation identity, start time,
text, reasoning summaries, tool argument strings, native call IDs and results.
It preserves role without guessing human authorship. Opaque state, signatures
and image bytes are excluded. An initial gap states that earlier context and
intermediate events may be absent. Duplicate result IDs fail before output.
Generated call IDs cannot pair with unrelated native result IDs.

Model identity, usage, approvals, settings, session relationships and per-message
timestamps are not exported. The header lists these losses. No session end or
original content interleaving is inferred from retained context.

Three domain tests, the main crate check, a debug CLI build, focused lint and
the JSON example passed. The CLI completed one synthetic turn through a local
model endpoint with the key in its native private provider files. The actual CLI
export validated. The committed sample comes from the synthetic fixture, which
avoids retaining generated system instructions from the live run.

To reproduce the packaged sample from an already patched checkout, run:

```bash
python3 upstream/forgecode/reproduce.py /path/to/patched/checkout
```

The reproduction uses temporary native fixture files, compares the exported
records with the packaged sample and runs the ASR validator. It does not start
inference. The package check runs in repository CI without fetching or compiling
the upstream project.

## Verification scope

The live evidence above is from a prior revision. The current source has focused
regressions and package checks. Its full agent and model path has not been rerun.
