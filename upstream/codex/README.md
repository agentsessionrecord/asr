# Codex native export design feedback

This is reference code for Agent Session Record (ASR) export in [Codex](https://github.com/openai/codex), offered for design feedback. The Codex [contribution policy](https://github.com/openai/codex/blob/main/docs/contributing.md) says it does not accept external code contributions or pull requests. Read the [proposal](PROPOSAL.md) for the design, runtime requirements and build instructions.

## Evaluate the reference implementation

The pinned base is `6b2a2757de696c2506ee460c49c66a8e2bed65e0`. [Apply the patches](../README.md#apply-a-patch) in a separate checkout at that base. On another base, regenerate the Cargo lockfile hunks with upstream tooling.

Codex's `/export` writes Markdown by default. The patches add `/export --format agent-session PATH` for saved local threads, plus these commands:

```sh
codex sessions export --format agent-session --all --output ./asr
codex sessions export --format agent-session --session NATIVE_THREAD_ID
codex sessions register
```

Saved rollouts and a read-only state snapshot supply messages, tools, settings, offered tools, approvals, model calls, usage and structured file changes. Mutable titles and pull request links go in separate annotations. Known credential fields and recognized secret text are left out.

The source does not establish every served model, approval, file edit, commit, setting or copied-history boundary. The exporter does not read attachments or current Git state to fill those gaps. The proposal lists the losses in detail.

## Checks

```sh
node upstream/codex/check.mjs
node upstream/codex/reproduce.mjs /path/to/upstream-checkout
```

See [package checks](../README.md#check-a-package). The focused build, tests, type check, Clippy and format checks pass, and [refresh.json](refresh.json) has the results. No live model run covers this revision.
