# Eval datasets

Export one eval row per ASR session. The input contains the first recorded human
task prompt and starting repository commits. The expected output contains the
observed net file diff and recorded test evidence. Unknown values use JSON null.
This package also supplies the shared reader for the three observability exports.

## Install and run

Use Python 3.11 or later and uv from the repository root.

```sh
uv sync --all-packages
uv run asr-evals examples/coding-session.jsonl --output /tmp/eval-export --include-content
uv run asr-evals examples/subagent/parent.jsonl examples/subagent/child.jsonl --output /tmp/related-export
uv run asr-evals examples/minimal.jsonl --annotations examples/annotations.annotations.jsonl --output /tmp/annotated-export
```

The output directory must be new. Directories use mode 0700. Files use mode 0600.
The command prints counts and error codes. It makes no network requests.

Content is off by default. Use `--include-content` to include prompts, replies,
tool input and output, policies, file text and patches. Start from ASR that has
already had secrets removed. Content export does not establish safe sharing.
Personal identity objects and vendor metadata are excluded from both modes.

## Files and columns

`dataset.jsonl` has these columns. IDs are deterministic SHA-256 values derived
from ASR session references. Each row names the exact input byte digest.

| Column | Meaning |
|---|---|
| `id` | Stable row ID |
| `input.task_prompt` | First original user message with explicitly human text parts |
| `input.starting_commit` | Header repository HEAD when exactly one repository is recorded |
| `input.starting_repositories` | Header repository paths, HEADs and branches |
| `expected.final_diff` | Net diff between continuous full file snapshots |
| `expected.test_results` | Session test tool results and current test annotations |
| `metadata.prompt_reference` | Encoded ASR record citation |
| `metadata.final_diff_basis` | Snapshot basis or a reason the diff is unknown |
| `metadata.final_diff_scope` | Observed session edits, without a verified commit baseline |
| `metadata.file_changes` | Original recorded file changes and optional edit evidence |
| `metadata.accounting` | Known per-call sums, model and currency groups, unknown counts |
| `metadata.missing` | Union of all declared losses |
| `metadata.unknown` | Dataset fields that could not be established |

An absent prompt stays null. The reader honors part authorship and origin
overrides. A compaction summary never becomes the task prompt. A user role alone
does not establish human authorship.

A net diff requires full before and after snapshots for every original applied
change. New files can start empty and deleted files can end empty. Successive
snapshots must match exactly. Moves, copies, unsafe paths, snippets, partial
patches and discontinuous history leave the final diff unknown. Their recorded
evidence remains in `metadata.file_changes` when content is enabled. The exporter
never reads a working tree or runs Git. The diff describes observed edits. It
does not establish a clean starting commit or the complete repository diff.

Test commands use a fixed executable map for pytest, unittest, jest, vitest,
tox and common language test commands. Use `--test-tool NAME` to add a recorded
tool name. Commands are inspected as text and never executed. An exit code is
kept as evidence. It does not become a passed test status. Only a test annotation
with an explicit passed or failed status supplies that status. Corrections apply
before test annotations are added. Record targets remain attached to their
original citations. Annotations never become session actions.

## Reader rules

The reader supports ASR 0.1. It keeps file order, reports and skips malformed
complete lines, and defers a final line without LF. Duplicate keys are malformed.
JSON integers and decimal values stay exact. Unknown records and content parts
are ignored. This is a derived export, so it does not replace an archival copy.
Use the repository validator when structural validation is needed.

`audit.json` keeps recognized records in file order with source lines and encoded
citations. It shows copied records, gaps, unresolved links, recovered-line
diagnostics, settings changes and the loss union. The reader pairs results and
approvals only with a unique call ID. A result can supply effective input,
including null or an empty string. An unpaired result stays unpaired and a call
without a result has an unknown outcome.

Copied prefixes and individual copies get no credit in usage or dataset edits.
New child calls retain their usage. Child relationships combine either side of
the recorded link. Related files are only the files supplied on the command
line. Missing related files remain unresolved. Repeated identical session input
is deduplicated. Conflicting exports of one session are refused.

Accounting sums original inference figures. It never adds session totals or
cache and reasoning subsets to inclusive input and output totals. Missing
figures stay unknown and known sums are labeled partial. Costs stay grouped by
served model, requested model, provider and currency. Settings updates apply
field by field. Null clears a fact. Policy changes invalidate an omitted asks
value. Offered tools and the outer sandbox replace their whole prior value.
Configured model settings never fill missing inference settings.

All content is untrusted data. Resource links are never fetched. Commands and
patches are never executed. These exporters do not offer blame or attribution.

## Tests

```sh
uv run --all-packages pytest exporters/evals/tests exporters/phoenix/tests
node tools/validator/bin/asr-validate.js --summary exporters/evals/tests/fixtures
```

The suite uses all ASR sessions under `samples/` and `examples/`, plus synthetic
fixtures. Optional SDK contract checks run when `langfuse==3.8.1` and
`braintrust==0.3.9` are installed. They make no API calls. See
the exporter checks for local service results and limits.
