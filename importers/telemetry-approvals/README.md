# Telemetry approval importer

Add Claude Code and Codex approval evidence to an existing ASR session.
The importer creates a new file and leaves its inputs intact.
It uses the Python ASR writer for new records.

## Run

From the repository root:

```sh
uv sync --all-packages
uv run --all-packages asr-import-approvals session.jsonl \
  --telemetry events.jsonl --output session-with-approvals.jsonl
node tools/validator/bin/asr-validate.js session-with-approvals.jsonl
```

Repeat `--telemetry` for files in their recorded order.
The command prints coverage counts.
The output must be a new file. It is created with owner-only permissions.

Inputs can be OTLP JSON log exports, concatenated OTLP JSON batches, arrays
of log records, or saved Node console log exporter output.
Both camel case and snake case OTLP field names are accepted.
Console data is parsed as data. Expressions and function calls are rejected.
Separate console telemetry from other console output before importing it.
Truncated console objects and invalid telemetry cause the command to fail
before writing an output file.

## Identity and placement

Claude Code events use `session.id` and `tool_use_id`.
When present, `agent_id` identifies a child instead of its parent session ID.
Codex events use `conversation.id` and `call_id`.
A root conversation ID does not identify its children.
A namespaced ASR session requires a matching `session.namespace` attribute
added by the collector. Without that evidence the join stays unresolved.

Independent telemetry has no shared record position with the transcript.
Each decision goes immediately before its unique matching result.
Decisions for one call keep telemetry input order, even when times disagree.
Only the recorded event time supplies `ts`. Receipt time is not substituted.
An unmatched decision, a call with no result, and an ambiguous call ID stay
in the header's `org.agentsessionrecord.telemetry-approvals` metadata.
These snapshots do not become stream decisions at an invented position.

An existing approval with matching native decision evidence is enriched once.
The importer preserves its ID and position. It retains repeated decisions.
An explicit event sequence and event time can identify a repeated delivery.
Without those fields, identical observations can be distinct decisions.
Reimporting the same events does not add the same approvals again.

The output names this importer as its converter producer.
`derivedFrom.sha256` hashes the exact input ASR bytes.
Unchanged records pass through byte for byte, including unknown fields and
exact numeric tokens. Altered records also retain exact numeric tokens.
Malformed source ASR records become gaps at their original positions.
An invalid header, duplicate IDs and duplicate results are rejected.

`approvals` remains in `missing`. Matching a decision to every call does not
prove that every decision was delivered. Coverage counts describe the join,
including calls with matched telemetry, and do not prove complete approval history.

## Mappings and supported sources

Mappings follow [Claude Code](../../agents/claude-code.md),
[Codex](../../agents/codex.md), and ASR-073 through ASR-075.
The native fixtures in `tests/fixtures` are synthetic.
The live test used Claude Code 2.1.305 and Codex 0.163.0.
The Codex decoder accepts the reviewed range 0.144.3 through 0.163.0.
It needs a source version from telemetry or the ASR agent header.
Other versions retain decision evidence as unknown metadata.

Claude Code `accept` means approved and `reject` means denied.
An explicit `user_abort` means cancelled.
Mode reasons, hooks, classifier verdicts and config decisions supply their
recorded deciders. A temporary or permanent grant does not establish a fresh
human answer. Temporary grants also leave their lifetime unknown.
A permanent grant supplies `always`.
A single correlated safety event can supply `once` or `session`.
Several candidate decisions or safety events leave that scope unknown.
Safety events enrich decisions and are not counted as extra decisions.
The safety event shape is tested from the published 2.1.307 documentation.
It was unavailable in the installed 2.1.305 live test.

Codex `approved` supplies `once` and `approved_for_session` supplies `session`.
Reviewed persistent amendment encodings supply `always`.
`denied` and `abort` mean denied. `timed_out` means cancelled.
`User` establishes a person's answer, `Config` means policy, and
`AutomatedReviewer` means classifier. `Config` does not establish a hook.
Unknown values remain unknown. Current policy files do not supply decisions.

## Capture locally

Claude Code supports an OTLP JSON logs exporter:

```sh
export CLAUDE_CODE_ENABLE_TELEMETRY=1
export OTEL_LOGS_EXPORTER=otlp
export OTEL_METRICS_EXPORTER=none
export OTEL_EXPORTER_OTLP_LOGS_PROTOCOL=http/json
export OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=http://127.0.0.1:4318/v1/logs
```

A local collector can write its received JSON batches to a file.
`OTEL_LOGS_EXPORTER=console` selects the console exporter instead.
See the [monitoring documentation](https://code.claude.com/docs/en/monitoring-usage#tool-decision-event).

Codex supports an OTLP JSON logs exporter in its per-run config:

```toml
[otel]
exporter = { otlp-http = { endpoint = "http://127.0.0.1:4318/v1/logs", protocol = "json" } }
metrics_exporter = "none"
trace_exporter = "none"
log_user_prompt = false
```

See the [configuration reference](https://developers.openai.com/codex/config-reference/).
The live test found that a forbidden execpolicy rule produced no Codex decision
event. Its allowed command did produce one. Code-mode wrapper calls also had
no corresponding decision events. The importer kept the known approval loss.
It joined the allowed command through the native completed item's ID.

## Tests and privacy

```sh
uv run --all-packages pytest importers/telemetry-approvals/tests
uv run --all-packages python importers/telemetry-approvals/tools/live_test.py --key-file "$ASR_PROVIDER_KEY_FILE"
```

Set `ASR_OPENAI_BASE_URL`, `ASR_OPENAI_MODEL`, `ASR_ANTHROPIC_BASE_URL` and
`ASR_ANTHROPIC_MODEL` to explicit endpoint URLs and model names. Both URLs must
use `127.0.0.1` with an explicit port. The live test reads the configured client
key from a private file and writes it to temporary private provider settings.
It runs one allowed and one refused command per agent with throwaway homes.
It starts a loopback OTLP receiver, checks native tool evidence, imports the
telemetry, validates both ASR files, stops the receiver by PID and deletes the
scratch tree. It prints counts and codes. It does not retain session text.
The sample conversion in this driver retains tool evidence only and declares
its other losses. It is not a general transcript converter.

The importer copies only decision evidence from telemetry.
It excludes prompts, arguments, account labels and other unrelated fields.
It rejects recognized credentials in the input ASR and withholds telemetry
observations whose decision evidence contains a recognized credential.
This does not establish that a file is safe to share.

Every ASR test output passes the independent Node validator.
Tests for unfinished calls and ambiguous IDs have expected pairing warnings.
The unfamiliar-record test has an expected unknown-type warning.
Live output and the committed mapping samples have no warnings.
