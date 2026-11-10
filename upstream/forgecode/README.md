# Agent Session Record export for ForgeCode

This patch adds ASR output to the conversation dump command in ForgeCode. The pinned base is `a22b49288856d5b3f3ca57e8532683d54a662c8c`. [Apply the patches](../README.md#apply-a-patch) in a clean checkout at that base. The [proposal](PROPOSAL.md) gives the upstream repository, runtime requirements, build steps and output options.

```sh
forge conversation dump ID --format agent-session > session.jsonl
```

The export keeps retained context, conversation identity, start time, text, reasoning summaries, raw tool arguments, native call IDs and results. It leaves out opaque provider state but does no general secret redaction. Earlier context and intermediate events can be missing. Models, usage, approvals, settings, relationships and per-message times are absent, and the export does not infer a session end or the original interleaving.

## Checks

```sh
node upstream/forgecode/check.mjs
node upstream/forgecode/reproduce.mjs /path/to/upstream-checkout
```

See [package checks](../README.md#check-a-package). The focused build, tests, type check, Clippy and format checks pass, and [refresh.json](refresh.json) has the results. A whole-crate `cargo fmt` flags one unchanged line. No live model run covers this revision.
