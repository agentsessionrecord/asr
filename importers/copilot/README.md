# Copilot API usage importer

Convert GitHub streamed Copilot request and response records into ASR.
The command reads saved files and makes no API calls.

Status: not live-tested. The envelope follows GitHub's usage record documentation
retrieved on 2026-11-01. The body profile supports completed Chat Completions JSON
on `/chat/completions`. Fixtures are synthetic. GitHub does not promise that all
Copilot surfaces use this body shape. Other endpoints and streaming deltas remain
metadata gaps rather than guessed conversations.

## Install and use

From the repository root, with Python 3.11 or later and uv:

```sh
uv sync --all-packages
uv run --all-packages asr-import-copilot usage.jsonl \
  --session-id native-session-id --output session.jsonl
node tools/validator/bin/asr-validate.js session.jsonl
```

First partition usage records using an independently recorded native session
join. Pass that native ID with `--session-id`.
The usage envelope has no documented session key, so this step is required.
Do not use a user ID, endpoint or time window as a guessed session identity.
Use `--namespace` only when session IDs repeat across installations.
The ASR agent name is `org.agentsessionrecord.copilot-api`.
The stream does not claim which Copilot client surface produced the traffic.

## Mapping and limits

| Source | ASR |
| --- | --- |
| `event_id`, millisecond `@timestamp` | Native or derived record identity and event time |
| Request `messages` | Context messages in source order without guessed authorship |
| `github_request_id` | Exact join to a unique preceding request |
| Completed response `id` | One inference per native provider response |
| Request `model`, response `model` | Distinct requested and served models |
| Response usage and detail counts | Inclusive input and output totals with cache and reasoning subsets |
| Response choices and `tool_calls` | Model replies and requested tool calls |
| Envelope `truncated: true` | A shortened metadata gap without parsing the body |

Bodies are JSON-encoded strings. Invalid bodies and unknown endpoints produce
gaps. Large native IDs remain exact strings in metadata.
Repeated provider response IDs do not add model usage again.
Conflicting observations produce a gap.
Ambiguous or absent request joins leave the requested model unknown.

Request histories describe model context. They do not establish new tool work.
Historical tool results stay in metadata. Response tool calls have no recorded
execution outcome. A validator warning for a call without a result is expected.
The importer does not infer approvals, applied edits, commit actions, human
authorship, subagent links or copy boundaries. Those limits stay in `missing`.
See the [shared safety rules](../vendor-core/README.md#safety-and-losses).

## Tests and source

```sh
uv run --all-packages pytest importers/copilot/tests
```

The [native fixture](tests/fixtures/usage.jsonl) includes a large synthetic user ID,
distinct model names, usage subsets and a tool request.
The [ASR sample](tests/fixtures/usage.expected.asr.jsonl) is its output.
Tests cover truncation, malformed bodies, historical context and duplicate
response observations.

Source: [GitHub agentic audit log events and Copilot API usage records](https://docs.github.com/en/copilot/reference/agentic-audit-log-events).
