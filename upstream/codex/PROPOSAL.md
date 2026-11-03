# Codex native export design feedback

Export a saved session in an open format that search and code history tools can read. The export keeps the source facts available for later review.

This proposal adds native ASR 0.1 export and discovery to Codex.
It applies to upstream commit `ff2346f33f851bd4e90c8e42ae60abcc7e7f293b`.
It supports the rollout types at that commit and Codex CLI 0.163.0 logs.

```sh
codex sessions export --format agent-session --all --output ./asr
codex sessions export --format agent-session --session <native-thread-id>
codex sessions register
```

A directory export writes one stream per session and a private inventory.
A single selected session can go to standard output. Diagnostics go to standard
error. Output directories must be new. Files use mode 600 and directories use
mode 700. Discovery registration is an explicit command.

The exporter reads saved rollouts and a read-only state snapshot. It records
messages, tool requests and results, settings, offered tools, approvals, model
calls, usage and structured file changes when the source supplies them.
Mutable titles and pull request associations use separate annotation files.

Updated tool results appear where their final version was recorded, with that time.
An approval saved only on a result goes immediately before that result.
Changed MCP and dynamic-tool arguments learned at completion go on the result.
Configured setting clears use JSON null. Identified model calls remain present
when their model is unknown. Wide native numeric values become exact strings.
Unsafe core counts are omitted and retained as strings in native metadata.
Unmapped native content uses `com.openai.codex/content`, with the source block
under `_meta.com.openai.codex.native`. Known parts beside it keep their order.

The source does not establish every served model, approval, tool definition,
file edit, commit, setting or copied-history boundary. The stream declares those
losses. Tool outcomes do not establish approval. Display output does not become
model-facing content. Attachments and current Git state are not read to invent
historical facts.

Run the focused Rust tests and clippy in `codex-rs`. Set `ASR_VALIDATOR` to the
reference validator CLI to validate generated test streams.

```sh
cargo test -p codex-session-export
cargo clippy -p codex-session-export --all-targets -- -D warnings
cargo fmt -p codex-session-export --check
```

Synthetic regressions and a fresh scratch session against a local OpenAI-compatible endpoint exercise the
export command. The current reference validator reported zero errors for the
exported sample and scratch session.

## Patch package

`manifest.json` records the upstream base, final source revision, ordered commits
and SHA-256 digests. Apply the series in a clean checkout at the recorded base.

1. The exporter crate, core mappings and regression tests.
2. Saved settings, offered tools and approval decisions.
3. CLI command wiring.
4. Explicit discovery registration.
5. Vendor content naming and native block preservation.

The series contains source and tests. This proposal stays in the patch package.

```sh
git am /path/to/asr/upstream/codex/patches/*.patch
```

Run the package checks from the ASR repository root.

```sh
node upstream/codex/check.mjs
node upstream/codex/reproduce.mjs /path/to/codex-checkout
```

The retained sample is synthetic. `validation.json` contains aggregate sample and
scratch-session results. No real session text is included.

To reproduce the sample, copy `samples/native/session.jsonl` into a new scratch
Codex home at the path below. Set `ASR_PACKAGE` to this package's absolute path
and `SCRATCH` to a new private scratch directory. Run from the patched checkout.

```sh
mkdir -p "$SCRATCH/sessions/2026/10/31"
cp "$ASR_PACKAGE/samples/native/session.jsonl" \
  "$SCRATCH/sessions/2026/10/31/rollout-2026-10-31T12-00-00-019a3c2e-7b1f-7d40-9e2a-5c8b1d3f6e70.jsonl"
cd codex-rs
cargo run -p codex-session-export --example export -- \
  export --all --codex-home "$SCRATCH" --output "$SCRATCH/bundle"
```

The one sample warning, `unknown-extension`, identifies the declared Codex
extension. The live stream also has six `unknown-type` warnings for retained
vendor records. Both are expected extension diagnostics.

## Verification scope

The live evidence above is from a prior revision. The current source has focused
regressions and package checks. Its full agent and model path has not been rerun.

## Contribution policy

Codex [contribution policy](https://github.com/openai/codex/blob/main/docs/contributing.md)
says it does not accept external code contributions or pull requests. This proposal
asks for design feedback. The local source series is reference material. Regenerate
Cargo lockfile changes with upstream tooling when evaluating it on another base.
