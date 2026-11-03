# OpenTelemetry exporter

Export ASR 0.1 sessions as OTLP/HTTP JSON traces and logs. Python 3.11 or later
is required. The exporter has no runtime dependencies.

## Install and run

From the repository root:

```sh
uv tool install ./exporters/otel
asr-otel examples/coding-session.jsonl --output /tmp/asr-otel-output
```

This example exports logs with zero spans. The sample has no session start and
end times, and operation timestamp meanings are unknown without `--contracts`.
That flag reads a JSON file that maps exact producer identities to documented
timestamp meanings. It does not add missing times. Sessions with recorded start
and end times can still produce a session span without a contract.

You can also run from source:

```sh
PYTHONPATH=exporters/otel/src python3 -m asr_otel \
  exporters/otel/tests/fixtures/session.jsonl \
  exporters/otel/tests/fixtures/child.jsonl \
  --contracts exporters/otel/tests/fixtures/contracts.json \
  --output /tmp/asr-otel-output
```

The output directory contains three files:

| File | Contents |
| --- | --- |
| `traces.json` | An OTLP `ExportTraceServiceRequest` |
| `logs.json` | An OTLP `ExportLogsServiceRequest` |
| `report.json` | Counts and diagnostic codes with source ordinals and line numbers |

The same inputs and options produce the same output. Files use mode `0600`.
New output directories use mode `0700`. An export replaces existing output
files. It refuses to replace an input file. Input streams stay untouched.

Add `--endpoint http://127.0.0.1:4318` to send the files to a local collector.
The exporter posts JSON to `/v1/traces` and `/v1/logs` below that base URL.
Only numeric loopback addresses are accepted. IPv6 loopback is supported.
HTTP proxies and redirects are disabled. URLs in ASR are never fetched.
A failed request or partial rejection returns a nonzero exit code. The files
remain available for inspection. Delivery has no automatic retry or durable
queue. Resending logs may create duplicates at a receiver. Span IDs are stable.

## Timing contracts

Read [the OpenTelemetry guide](../../guides/otel.md). Session spans require
recorded `startedAt` and `endedAt`. The last supplied original `session_info.endedAt`
replaces the header value. A session interval that excludes recorded original
activity is omitted. End of file never supplies an endpoint.

An operation's `ts` does not establish its timestamp meaning. Supply a local
contract only after checking the producer's documentation. The fixture contract
applies only to the synthetic producer in this directory. It establishes no
timestamp meaning for another producer.

The contract file has a `producers` array. Each entry matches the complete
`name`, `version`, `method` and optional `source` in the ASR producer identity.
Unknown fields, duplicate identities and invalid values are rejected.

| Contract field | Meaning |
| --- | --- |
| `producer` | Exact producer identity to which the documented mapping applies |
| `inferenceTimestamp` | `start`, `end` or `unknown` for an inference's `ts` |
| `toolCallTimestamp` | `start` or `unknown` |
| `toolResultTimestamp` | `end` or `unknown` |
| `basis` | `source` or `receipt`. The default is `receipt` for recorders and `source` otherwise |
| `inferenceIdIsResponse` | Set `true` only for documented provider response IDs |
| `responseIdMetaPath` | Keys below `_meta` leading to a documented provider response ID |
| `serviceTier` | `request`, `response` or `unknown` |
| `reasoningEffortIsRequest` | Set `true` only for a documented requested reasoning level |

Omitted timestamp meanings stay unknown. An inference needs a documented
timestamp meaning and `durationMs`. A tool span needs a unique call and result,
a documented call start, and a documented result completion or recorded result
duration. Recorded completion takes precedence over duration. Negative intervals
are rejected. Nanosecond precision is retained. Times before the Unix epoch,
leap seconds and precision finer than nanoseconds are unsupported and reported.

Each session has its own deterministic trace ID. Each selected header, inference
or call has one deterministic span ID. Tool nesting uses `parentCallId` or
`inferenceId`. A missing parent span leaves a timed child without that parent.
Subagent links from either file join the relationship. Cross-session links use
OTLP span links so each session retains its trace ID. Missing files are never
opened automatically. Conflicting subagent relationships remain unresolved.
Native trace context in vendor metadata is unsupported.

## Attributes, logs and accounting

The exporter implements the revisions pinned by the guide:

- GenAI and OpenAI conventions: `72e0d0a097db3ba31ba3f33d0519401a044f6e23`.
- Core user and error conventions: `debfc1c62dcaf49eece43e3ee1d56a92b837a7e2`.

These revisions appear in instrumentation scope attributes. GenAI and user
conventions are under development. Upgrade this mapping deliberately when those
conventions change.

| Recorded fact | OTLP mapping |
| --- | --- |
| Session | `invoke_agent` span when both endpoints are established |
| Timed model call | `chat` span with requested and served models kept separate |
| Timed tool call | `execute_tool` span with the recorded tool name and call ID |
| Provider and model identities | `gen_ai.provider.name`, `gen_ai.request.model`, `gen_ai.response.model` |
| Per-call usage | Inclusive `gen_ai.usage.*` counts, preserving recorded zero |
| Per-call limits and temperature | `gen_ai.request.max_tokens`, `gen_ai.request.temperature` |
| Requested reasoning level | `gen_ai.request.reasoning.level` when established by the contract |
| OpenAI service tier | One of `openai.request.service_tier` and `openai.response.service_tier` when established |
| Provider response ID | `gen_ai.response.id` only when established by the contract |
| Stop reason | A one-element `gen_ai.response.finish_reasons` list |
| Failed result or recorded inference error | Error span status and a compatible recorded code in `error.type` |
| Approval, gap or settings update | A log, plus an event when its recorded timestamp fits the target span |
| Other known records | Logs with ASR identity and selected descriptive metadata |
| Custom facts and ambiguous meanings | Attributes under `asr.` |

Custom IDs use `asr.session_ref` and `asr.record_id`. This exporter uses the
task's `asr.` prefix for custom attributes, including the guide's custom identity
fields. It does not assign an undefined semantic convention to approval policy,
cost, native settings or agent mode.

Logs retain file order and carry `asr.record.index`. They omit time when ASR
omits it. Gaps retain their reason and known count. Missing information is the
union of all loss declarations. Unpaired results and unresolved references are
marked with `asr.unresolved_references`. Diagnostic codes explain skipped
spans and recovery. Malformed complete lines are reported and skipped.
An incomplete final line is deferred. Unknown record types are ignored and
reported. This is a derived telemetry view, not an ASR archival store or a
substitute for the validator.

Copies remain visible in logs with `asr.copied: true`. They receive no spans,
events, cost attributes or usage attributes. New child calls count as the
child's work. A missing copied-prefix boundary excludes every later record
from credit and produces a diagnostic.

Usage appears once per original inference, on its span when timed and otherwise
on its log. Input already includes cache reads and writes. Output already
includes reasoning. Source session totals stay separate under
`asr.source_session_total.*` on the header log. Each supplied usage or cost object
replaces that prior total. Children are never added to a reported session total.
Unknown counts and costs stay absent.

Settings logs retain the raw update and the effective state under
`asr.agent_settings.effective`. Omitted settings retain their prior values.
Null clears a setting. Model settings merge by field. An outer sandbox replaces
the prior object. Policy changes invalidate an omitted `asks` value.
Configured model settings never fill in a call's missing request settings.

## Content and personal data

Prompts, replies, tool arguments, tool output, error messages, gap details,
approval native values and tool definitions are omitted by default. Use
`--include-content` only when your data handling policy permits exporting the
recorded content. The opt-in adds `asr.record.json`. It keeps exact JSON numbers
and recorded part order. It also exports the uniquely paired tool result's
effective input, including a supplied empty string or null. Encrypted reasoning
remains without content.

Session user fields and structured message or approval identities require
`--include-identity`. A session name with unknown meaning uses `asr.user.name`.
Use `--user-name-kind short` or `--user-name-kind full` only when that meaning
is established. The session user label supplies no authorship or blame claim.
Free text can contain personal data even when structured identities are omitted.

Content is always data. The exporter never executes recorded commands, resolves
resource links, reconstructs model input from nearby messages or accesses recorded
file paths. ASR validation does not establish that content is safe to share.
Apply redaction and your sharing policy before enabling content export.

## Tests

Install the repository's locked Node dependencies for fixture validation:

```sh
pnpm install --frozen-lockfile
bash exporters/otel/check.sh
python3 exporters/otel/tests/collector_smoke.py
```

The unit tests use synthetic fixtures, all ASR files in `samples/*/asr`, and all
session examples. They cover framing recovery, exact IDs and numbers, span
timing, pairing, copies, settings, usage, content policy, local HTTP delivery and
collector rejection. The fixture streams pass the repository's Node validator.

The separate smoke test runs `otel/opentelemetry-collector-contrib:0.139.0`
in a disposable local Docker container. It posts both signals and reads the
Collector's file exporter output. It checks counts, IDs, timestamps, attributes,
links and events. It stops and removes its container and temporary files.
Use `--sudo` if Docker requires passwordless sudo. CI runs the unit tests.
The container test is explicit so CI does not require Docker access.
