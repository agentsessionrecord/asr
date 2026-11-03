# Braintrust export

Write offline span rows and eval dataset rows for Braintrust's v1 insert API.
The mapping is checked against Python SDK 0.3.9. Generation needs no account,
SDK or service.

## Install and run

Use Python 3.11 or later and uv from the repository root.

```sh
uv sync --all-packages
uv run asr-braintrust examples/coding-session.jsonl --output /tmp/braintrust-export
uv run asr-braintrust exporters/evals/tests/fixtures/session.jsonl --output /tmp/braintrust-content --include-content --inference-ts end --tool-times
```

The output directory must be new. Content is off by default.
The [shared reader and dataset rules](../evals/README.md) apply to every output.

## Import files

`project-logs.json` is an insert body with an `events` array for
`POST /v1/project_logs/{project_id}/insert`. The selected project supplies the
destination identity. Each row has stable `id`, `span_id`, `root_span_id`,
`span_parents`, `span_attributes` and metadata. Session roots use task spans.
Original model calls use llm spans. Tool calls use tool spans. Other original
facts use function spans with event evidence in metadata.

`dataset-insert.json` is an `events` body for
`POST /v1/dataset/{dataset_id}/insert`. Each row has input, expected output,
metadata and a stable ID. `dataset.jsonl` contains the same portable rows.
`audit.json` contains the shared reader evidence.

This CLI writes files. It makes no API calls. The files can be reviewed and
loaded by a separately configured client.

## Mapping and limits

Known input and output counts map to `metrics.prompt_tokens` and
`metrics.completion_tokens`. `metrics.tokens` appears only when both are known.
Cache and reasoning subsets remain metadata. Recorded USD costs use the custom
numeric metric `cost`. Other currencies remain metadata. Unknown counts and
costs are omitted. Copies and session totals do not add metrics.

Untimed operations retain their metrics with start and end omitted. Native
timestamp meanings are unknown by default. Use `--inference-ts start` or
`--inference-ts end` only with the producer's documented timestamp contract.
Use `--tool-times` only with recorded call start and result completion meanings.
Recorder pairs can use labeled receipt intervals. Time values are Unix seconds.
Unknown outcomes remain metadata and never become success. Served and requested
models remain separate metadata fields. Model inputs are never reconstructed.

The SDK log argument validator checks the generated span rows locally. A real
Braintrust service has not been exercised. No account was created. See
the exporter checks.

## Contract references

- [Project log insert](https://www.braintrust.dev/docs/api-reference/projectlogs/insert-project-logs-events)
- [Dataset insert](https://www.braintrust.dev/docs/api-reference/datasets/insert-dataset-events)
- [SDK 0.3.9](https://pypi.org/project/braintrust/0.3.9/)

## Tests and status

From the repository root, run the shared reader, mapping and SDK contract tests:

```sh
uv run --isolated --package asr-phoenix --with 'pytest>=8.3,<10' \
  --with-editable exporters/langfuse --with-editable exporters/braintrust \
  pytest exporters/evals/tests
```

The suite checks synthetic fixtures, sample and example sessions, exact numbers,
usage, copy accounting, missing times and the pinned SDK request shapes.
Live-test status: **not-live-tested**. No service account or endpoint was used.
