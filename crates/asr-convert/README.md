# Native log converters

`asr-convert` turns a native file or directory into one ASR file per native session.
It reads local data and never follows recorded links or executes recorded commands.
It supports the native source profiles listed below.

```sh
cargo run -p asr-cli -- agents
cargo run -p asr-cli -- convert --agent claude-code native-logs --out converted
cargo run -p asr-cli -- convert --agent codex native-rollouts --out converted
cargo run -p asr-cli -- validate --summary converted
```

The output directory has mode 700 on Unix. Output files have mode 600.
Existing output for the same session is replaced atomically after conversion succeeds.
Keep converted history private. Validation does not make it safe to share.

## Install and supported sources

Install the [ASR CLI](../asr-cli/README.md#install) from this checkout.
For library use, add `asr-convert` as a local path dependency in a Rust consumer.
The CLI's `asr agents` output lists selectable names.

| Source group | Agents | Mapping and limits |
| --- | --- | --- |
| Transcripts | Claude Code, Codex | [Coverage below](#adapter-coverage) |
| Documents and snapshots | Cursor, Gemini CLI, Mistral Vibe, Xum, legacy Mux, fx | [Source contracts](ADAPTERS-W1A.md) |
| Native JSONL | Antigravity, Tabnine, Qoder, Droid, Copilot CLI, Qwen Code, Grok Build, Pi, Kimi Code, DeepSeek harness, Junie, legacy OpenClaw | [JSONL profiles](src/jsonl/README.md) |
| Stored documents | Auggie, Cline, CodeBuddy, Continue, Hermes, NanoClaw, OpenHands, Roo Code, Rovo Dev | [Document source profiles](tests/fixtures/documents/README.md) |
| Databases | AstrBot, Crush, Qoder CN, Shelley, Deep Agents, ForgeCode, OpenCode, Kilo Code, MiMoCode, Zed, Devin, Firebender, Goose, Kiro, Warp, OpenClaw | [Database profiles](DATABASE-ADAPTERS.md) |

The OpenClaw selector accepts both supported SQLite and legacy JSONL layouts.
Source profile support does not establish compatibility with every agent release.

## Add an agent

1. Add its name, metadata domain and source name to `Agent`.
2. Teach `source.rs` to read its native identity from recorded metadata.
3. Add a module that projects native observations through `Context`.
4. Use `Context::emit` for ordinary records and `Context::result` for result updates.
   Supply a fold key only for observations of the same native item.
5. Add a synthetic native sample, a golden export and source comparison assertions.
6. Declare every unsupported mapping through `Context::loss`.
7. Register the adapter and run the Rust checks and the Node validator.

The public API is `convert(&Options)`. `Summary` contains counts, diagnostic codes
and `session_diagnostics` keyed by recorded session reference. A malformed projected
record becomes a declared gap. A failed session does not stop independent sessions.
The CLI returns a nonzero exit status when a session or source fails.
See [source evidence and attribution](MAPPINGS.md) for all 43 authorship and
repository mappings, reasoning labels and recovery rules.
`Options::max_record_bytes` defaults to 16 MiB. It bounds source lines, retained
assembled content and the in-memory set of known secrets.

## Reading and staging

The reader drains oversized complete lines and writes a gap in their position.
Malformed JSON, duplicate keys and invalid UTF-8 also produce a gap.
An incomplete final line is deferred and counted as `incomplete_source_tail`.
A file without a recorded session identity is counted as `unidentified_source`.
A filename never supplies a guessed identity.

Sources can be plain JSONL or Zstandard JSONL. An uncompressed companion takes
precedence over its compressed copy. Directory symlinks are not traversed.
Canonical file aliases are read once. A SQLite index holds native observations,
folded projections and reserved IDs. Its cache is 4 MiB and temporary sorting uses
disk. Memory depends on the record limit and directory traversal depth.
The private staging directory is removed when conversion returns, including errors.
Projection and output each stream through one SQLite cursor. Repeated writes use
cached statements. Approval snapshots use an indexed prefix range when a result
moves to its completion point. They do not scan unrelated folded records.

Known credential fields, recognizable token forms and explicitly secret answers
are excluded before projection. Matching values stay in a bounded memory database.
Opaque reasoning state and provider signatures are excluded.
Newly discovered losses stay in the header. Text shortened by redaction or a size
limit is marked, and a size limit that removes a record produces a gap.

## Order and identity

File order is evidence. Timestamps never sort a stream.
A folded record moves to its final contributing observation and takes that time.
Intervening records keep their positions. A snapshot approval has no borrowed
result timestamp and goes immediately before its folded result.
A record with a native source position keeps that position.

Unique source IDs are retained. Other IDs use SHA-256 over length-framed native
identity or source-position components. References percent-encode reserved bytes.
Large native numeric values become exact strings. ASR reading preserves number
tokens, including decimals and integers outside machine integer ranges.

## Adapter coverage

Claude Code supports the synthetic 2.1.305 transcript and the documented
2.1.219 through 2.1.305 shapes where their fields are present.
It folds repeated UUID snapshots at their last observation and emits one inference
per provider response ID. It keeps messages, tool calls and outcomes, offered
tools, recorded request settings, permission snapshots and file result evidence.
Unknown events stay under the agent metadata domain.

Codex supports the synthetic 0.163.0 rollout and the documented 0.144.3 through
0.163.0 shapes where their fields are present. It handles response items,
turn context, usage records, session totals, execution completions and file changes.
Its thread identity is the recorded `session_meta.id`. The spawn tree's root
`session_id` stays in vendor evidence. A native rollout filename can select a
matching recorded thread ID when ancestor metadata is present. A filename never
creates an identity. Ambiguous metadata without corroboration is counted as
`unidentified_source`.
A recorded response ID establishes an inference even without a model.
Turn configuration supplies a requested model and never a guessed served model.
Ordinary rollout events do not establish approval decisions.

Both adapters declare partial capture. They do not discover sidecars or external
tool-output files, join telemetry or reconstruct full native trees.
Unsupported evidence remains in vendor metadata when it is
safe to retain. Missing declarations describe these limits.

## Tests

`cargo test --workspace` runs source recovery, folding, privacy and golden checks.
The committed goldens come only from the synthetic samples in `samples/`.
Those samples include editorial changes and another producer's metadata, so the
new exports have their own goldens. The implementation report explains differences.

For bounded qualification, run `scripts/check-sample.py`.
It accepts the same binary, validator, output and root arguments as the corpus check.
It selects up to 300 files per agent across six stored-size ranges and includes
the ten largest eligible files. File aliases and compressed companions are excluded.
Use `--jobs` to bound parallel work. Each file has a five-minute conversion and
validation budget. A timeout removes its incomplete output and retains aggregate
timing evidence. Private catalogs map report IDs to native paths. Summaries include
diagnostic counts, conversion time percentiles and the ten slowest files per agent.
Timeouts are censored observations. Their full conversion duration is unknown.

For a private local corpus, run `scripts/check-corpus.py`.
Pass `--binary`, `--validator`, `--out` and one or more `--root agent=directory`.
Use `--jobs` to bound the number of independent directory batches running at once.
The default is one batch. Aggregate results are written by one controller.
Large directories are split at recorded session identities, with a target of 128
files per batch. A session's files stay together. Compressed discovery uses the
`zstd` command. The first run saves a private input catalog for later resumes.
Use a fresh output directory to check a different input selection.
It checks every selected file, validates each output batch and writes counts.
A batch with no identified session keeps its conversion diagnostics and causes
the harness to exit with code 1.
Keep its output outside the repository. It starts no agent sessions.

## Performance checks

Set `ASR_CONVERT_PROFILE=1` to write JSON phase timings to stderr. The phases are
`staging`, `privacy`, `projection` and `output`. Timings contain no native paths,
session identities or recorded text. Exported ASR and the stdout summary stay the same.

Run `scripts/check-performance.py` on Linux with GNU time.
Pass `--catalog` from a previous sample run, `--binary`, `--validator`, `--out` and
one or more `--reference` directories containing prior exports by sample file ID.
Each reference can store files directly under that ID or in its `asr` subdirectory.
The check runs one converter at a time with a 120 second conversion deadline.
Validation has its own 300 second deadline. It records per-process peak RSS, CPU
time, wall time, phase timings and diagnostic counts. Every output is compared
byte for byte, including its filename, and validated with the Node validator.
Source hashes before and after conversion detect concurrent history changes.
Missing references and changed bytes fail the check.

Completed measurements are saved for resuming. Use `--recheck` to repeat output
comparisons after supplying missing reference exports, without repeating
conversion or validation. Source hashes describe the bytes measured in that run.
Later appends do not invalidate a completed comparison of the measured exports.
Use a fresh output directory after changing
the converter binary or the sample catalog. Keep all catalogs and exports private.

## Test status

All 44 registered converter profiles remain **not-live-tested**. Synthetic
native fixtures and exact ASR goldens cover their supported mappings. Bounded
local-history qualification is separate from starting a fresh agent and checking
its output. A passing plugin or native patch run does not qualify a converter.
The core library's independent live-test status is not applicable.

For focused checks from the repository root:

```sh
cargo test -p asr-convert
node tools/validator/bin/asr-validate.js --summary crates/asr-convert/tests/golden
node tools/validator/bin/asr-validate.js --summary crates/asr-convert/tests/golden-w1-conv-a
node tools/validator/bin/asr-validate.js --summary crates/asr-convert/tests/jsonl-b/golden
```

Partial capture declarations and expected vendor extension, unknown-type and
unpaired-tool warnings describe source limits. Zero validation errors do not
establish that every native event was observed.
