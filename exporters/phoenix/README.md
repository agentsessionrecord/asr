# Phoenix export

Write OpenInference OTLP traces and dataset upload files for Phoenix 12.23.0.
The binary transport uses `opentelemetry-proto==1.45.2`. Attribute names follow
`openinference-semantic-conventions==0.1.43`.

## Install and run

Use Python 3.11 or later and uv from the repository root.

```sh
uv run --isolated --package asr-phoenix asr-phoenix examples/coding-session.jsonl --output /tmp/phoenix-export
uv run --isolated --package asr-phoenix asr-phoenix exporters/evals/tests/fixtures/session.jsonl --output /tmp/phoenix-content --include-content --inference-ts end --tool-times --dataset-name synthetic-evals
```

Use a separate environment from the Envoy recorder. Its `xds-protos` dependency
ships older OpenTelemetry modules that overlap with `opentelemetry-proto`.

The output directory must be new. Content is off by default.
The [shared reader and dataset rules](../evals/README.md) apply to every output.

## Import files

`traces.otlp.pb` is an OTLP `ExportTraceServiceRequest` for `POST /v1/traces`
with content type `application/x-protobuf`. `traces.otlp.json` is the equivalent
OTLP JSON representation with hex trace and span IDs. The pinned Phoenix
endpoint accepts the binary representation.

`dataset-upload.json` is a `POST /v1/datasets/upload` JSON body with name,
inputs, outputs and per-example metadata. It creates a named dataset. Choose a
fresh name with `--dataset-name NAME` when importing again. The default is
`asr-evals`. Source row IDs stay in metadata.

`dataset.jsonl` and `audit.json` are portable offline evidence.
`omitted.json` lists operations without established timing.

## Local import

For an already running local Phoenix instance, explicitly load the files:

```sh
uv run --isolated --package asr-phoenix asr-phoenix-load-local /tmp/phoenix-content --endpoint http://127.0.0.1:6006
```

The loader allows only literal `127.0.0.1` or `::1` HTTP origins. It ignores proxy
environment variables and refuses redirects. It has no cloud destination,
credential lookup or automatic retry. The endpoint comes from the CLI.
Export generation itself never opens a socket.

## Mapping and limits

Sessions become AGENT spans, model calls become LLM spans and unique tool pairs
become TOOL spans. Recorded inclusive input and output counts map to
`llm.token_count.prompt` and `llm.token_count.completion`. Only a served model
fills `llm.model_name`. Requested models, exact costs, cache and reasoning
subsets remain `asr.*` metadata. Session totals and copies add no spans or usage.
Successful-looking exit codes do not set span success. Recorded failures set
error status. Other outcomes leave status unset and keep their recorded meaning.

Session spans require recorded start and end times. Native inference and tool
timestamp meanings remain unknown by default. Use `--inference-ts start` or
`--inference-ts end` only with a documented producer contract. Use `--tool-times`
only when call and result timestamps identify start and completion. Recorder
pairs can use labeled receipt intervals. Missing endpoints never use export
time or neighboring events. Timed children survive when their parent is untimed.
An interval outside its parent's bounds leaves the span without that parent.
Sessions with work outside their recorded end omit the root span.

Timed non-operation facts become events on an available session span. All facts
remain in the audit file. Unknown timing can produce an empty OTLP request.
Linked replies are observed output data. They do not establish exact model
context. No tools, resources or commands from a stream are executed or fetched.

See the exporter checks for the local import evidence.

## Reproduce the local service test

Use a separate Python 3.12 service environment. The test uses synthetic data,
starts a loopback server, imports both files and reads them back. It terminates
its own process and removes the temporary database. The log path must be new.

```sh
uv venv --python 3.12 /tmp/phoenix-test-env
uv pip install --python /tmp/phoenix-test-env/bin/python -r exporters/phoenix/tests/requirements-live.txt
uv run --all-packages python exporters/phoenix/tests/live_local.py --service-python /tmp/phoenix-test-env/bin/python --log-file /tmp/phoenix-test.log
```

The pinned service uses Python 3.12. The exporters also run on Python 3.14.
Broad service dependency ranges need the companion version pins in this test.

## Contract references

- [Phoenix 12.23.0](https://pypi.org/project/arize-phoenix/12.23.0/)
- [OpenInference conventions](https://github.com/Arize-ai/openinference/tree/main/spec)
- [OTLP JSON mapping](https://opentelemetry.io/docs/specs/otlp/#json-protobuf-encoding)
