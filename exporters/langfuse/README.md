# `Langfuse` export

Write offline trace ingestion and dataset item requests for `Langfuse`.
The contract is the public ingestion API represented by Python SDK 3.8.1.
No SDK, account or service is needed to generate the files.

## Install and run

Use Python 3.11 or later and uv from the repository root.

```sh
uv sync --all-packages
uv run asr-langfuse examples/coding-session.jsonl --output /tmp/langfuse-export
uv run asr-langfuse exporters/evals/tests/fixtures/session.jsonl --output /tmp/langfuse-content --include-content --inference-ts end --tool-times
```

The output directory must be new. Content is off by default.
The [shared reader and dataset rules](../evals/README.md) apply to every output.

## Import files

`ingestion.json` is the body for `POST /api/public/ingestion`. It contains
`trace-create`, `generation-create`, `span-create` and timed `event-create`
events. A trace groups one session. Original inferences become generations and
unique tool pairs become spans when their intervals are established. IDs derive
from encoded ASR citations. The envelope timestamp records export creation.
It is separate from recorded event and operation times.

`dataset-items.jsonl` contains one body per `POST /api/public/dataset-items`
request. Create the named dataset first using `POST /api/public/datasets`.
The default dataset name is `asr-evals`. Change it with `--dataset-name NAME`.
Input, expected output and metadata follow the shared dataset schema.

These are import files. This CLI does not send them to any endpoint.
`dataset.jsonl` and `audit.json` are also written for offline review.

## Mapping and limits

A recorded served model fills `model`. A requested alias remains metadata.
Call settings fill `modelParameters`. Inclusive counts fill `usageDetails.input`
and `usageDetails.output`. A total is supplied only when both are known. Cache
and reasoning subsets remain metadata so they are not counted twice.
Only recorded USD costs fill `costDetails.total`. Other currencies remain
metadata. Session totals and copies never become generation metrics.

No timestamp meaning is assumed for native tool or model records. Pass
`--inference-ts start` or `--inference-ts end` only when the producer documents
that meaning. Pass `--tool-times` only when call and result timestamps identify
start and completion. Recorder tool pairs can use receipt intervals, labeled as
such. No neighboring timestamps or export times fill operation endpoints.
Untimed operations remain in `audit.json` and are listed in `omitted.json`.

A trace with no recorded start omits its body timestamp and marks it unknown.
The service may display its own ingestion time. That time is not ASR evidence.
Timed messages, approvals, gaps, settings, file changes and VCS facts are event
metadata. Untimed facts remain in the audit file. Linked output messages are
observed outputs. They do not reconstruct a model request.

The pinned SDK request models are checked locally. A self-hosted service has
not been exercised. No account was created. See the exporter checks.

## Contract references

- [Public ingestion](https://api.reference.langfuse.com/ingestion/batch)
- [Dataset items](https://api.reference.langfuse.com/dataset-items/create)
- [SDK 3.8.1](https://pypi.org/project/langfuse/3.8.1/)

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
