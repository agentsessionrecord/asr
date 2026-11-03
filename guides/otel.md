---
title: "OpenTelemetry"
description: "Export recorded model and tool activity to OpenTelemetry GenAI spans."
---

This guide maps ASR to [OpenTelemetry's GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/). Attribute names are checked on October 30, 2026 against the [GenAI registry](https://github.com/open-telemetry/semantic-conventions-genai/blob/72e0d0a097db3ba31ba3f33d0519401a044f6e23/model/gen-ai/registry.yaml), [GenAI spans](https://github.com/open-telemetry/semantic-conventions-genai/blob/72e0d0a097db3ba31ba3f33d0519401a044f6e23/model/gen-ai/spans.yaml), [OpenAI registry](https://github.com/open-telemetry/semantic-conventions-genai/blob/72e0d0a097db3ba31ba3f33d0519401a044f6e23/model/openai/registry.yaml), [user registry](https://github.com/open-telemetry/semantic-conventions/blob/debfc1c62dcaf49eece43e3ee1d56a92b837a7e2/model/user/registry.yaml) and [error registry](https://github.com/open-telemetry/semantic-conventions/blob/debfc1c62dcaf49eece43e3ee1d56a92b837a7e2/model/error/registry.yaml). The GenAI and user conventions are under development. An exporter should name the revisions it implements.

This guide adds no requirements. ASR supplies a record for search and blame. OpenTelemetry supplies timed operations for monitoring. Exporting spans does not turn a session into an exact account of model input or a complete performance trace.

## Use recorded timing

A span needs a start and an end. Emit it only when the source establishes both, or establishes a start and a duration. `ts` alone does not say whether it marks an operation's start or completion. Use the producer's documented timestamp meaning.

| ASR source | Span | Timing needed |
|---|---|---|
| Session header and latest `session_info` | `invoke_agent` | Recorded `startedAt` and `endedAt`. |
| `inference` | `chat`, or the recorded provider operation | A documented start `ts` and `durationMs`, or equivalent observed endpoints. |
| Uniquely paired `tool_call` and `tool_result` | `execute_tool` | Recorded call start and result completion, or recorded start and result `durationMs`. |
| A linked child session | `invoke_agent` for the child | The child's own recorded endpoints. |

Do not borrow time from neighboring records or use export time to fill a missing endpoint. End of file is not a session end. A session that resumes can have work after a recorded end, so check that the chosen interval actually describes the exported activity.

Recorder receipt times can describe the observation interval. Label that basis in exporter metadata instead of presenting it as measured agent execution time.

When a parent's span cannot be emitted, keep timed children without that parent. A child's `parent.callId` can connect its session span to the delegating tool span. `parentCallId` can connect a nested tool span to its enclosing tool. Unresolved links remain unresolved.

## Map attributes without changing their meaning

| Attribute | ASR value |
|---|---|
| `gen_ai.operation.name` | `invoke_agent`, `chat` or `execute_tool`, as applicable. |
| `gen_ai.conversation.id` | Native `sessionId`. |
| `gen_ai.agent.name` | `agent.name`. |
| `gen_ai.agent.version` | `agent.version`. |
| `user.id` | `session.user.id`. |
| `user.email` | `session.user.email`. |
| `user.name` | `session.user.name` when the source establishes a short name or login name. |
| `user.full_name` | `session.user.name` when the source establishes a full name. |
| `gen_ai.provider.name` | `inference.model.provider`. |
| `gen_ai.request.model` | `inference.model.requested`. |
| `gen_ai.response.model` | `inference.model.id`. |
| `gen_ai.response.id` | `inference.id` only when the producer documents it as the provider's response ID. |
| `gen_ai.response.finish_reasons` | A list containing the recorded `stopReason`. |
| `gen_ai.request.reasoning.level` | `inference.settings.reasoningEffort` when it records the requested reasoning level. |
| `gen_ai.request.max_tokens` | `inference.settings.maxOutputTokens`. |
| `gen_ai.request.temperature` | `inference.settings.temperature`. |
| `openai.request.service_tier` | `inference.settings.serviceTier` for an OpenAI call when the source establishes the requested tier. |
| `openai.response.service_tier` | `inference.settings.serviceTier` for an OpenAI call when the source establishes the tier used for the response. |
| `gen_ai.usage.input_tokens` | `usage.inputTokens`. |
| `gen_ai.usage.output_tokens` | `usage.outputTokens`. |
| `gen_ai.usage.cache_read.input_tokens` | `usage.cacheReadTokens`. |
| `gen_ai.usage.cache_write.input_tokens` | `usage.cacheWriteTokens`. |
| `gen_ai.usage.reasoning.output_tokens` | `usage.reasoningTokens`. |
| `gen_ai.tool.name` | `tool_call.name`. |
| `gen_ai.tool.call.id` | `callId`. |
| `agent_session.session_ref` | The ASR session reference. |
| `agent_session.record_id` | The record from which the span is exported. |

ASR input counts already include cache reads and writes. Output counts already include reasoning. Export the counts without adding those subsets again. The pinned convention names cache writes `gen_ai.usage.cache_write.input_tokens`. A derived inference ID is an ASR identity, so keep it in `agent_session.record_id` without presenting it as a provider response ID. A documented provider response ID retained in the agent's `_meta` can instead supply `gen_ai.response.id`.

The two `agent_session.*` attributes are custom attributes defined by this guide. The other names in the table are semantic conventions. Export recorded request settings without inventing defaults. Apply settings recorded for a turn to each of its established inference spans.

Include user attributes only when the export policy permits personal data. Put them on the session span and any child operation spans that need that grouping. Do not guess whether `user.name` is a login or a full name. If its meaning is unknown, leave it in ASR. The label does not establish message or commit authorship.

There is no provider-neutral service-tier attribute in the checked conventions. Do not map another provider's tier to an `openai.*` attribute, or fill both request and response tiers from one undifferentiated value. Leave the tier in ASR when the provider or its meaning is unknown.

The checked conventions have no standard attributes for approval decisions, `asks`, `externalSandbox`, native agent policies, `user.source` or message triggers, and configured `modelSettings` do not establish request attributes. Keep those facts in ASR and see the [audit guide](audits.md) for importing vendor decision events.

```jsonl
{"type":"inference","id":"response-7","ts":"2026-10-26T14:02:11Z","model":{"provider":"example","requested":"code-latest","id":"code-model-1"},"durationMs":850,"usage":{"inputTokens":1200,"cacheReadTokens":800,"outputTokens":120,"reasoningTokens":20}}
```

If this producer documents `ts` as the call start, the span ends 850 milliseconds later. Its input is 1,200 tokens and output is 120 tokens. Without that timestamp contract, export the usage through a suitable reporting path and omit the span.

A failed tool result or an inference with `error` can set span status to error. Use a recorded error code for `error.type` where compatible. Do not infer tool failure from a nonzero exit code when the source does not.

## Identity and counting

For repeatable exports, derive a trace ID from the first 16 bytes of SHA-256 over the UTF-8 session reference without a fragment. Derive each span ID from the first 8 bytes of SHA-256 over the UTF-8 record reference `<sessionRef>#<recordId>`, with the record ID percent-encoded by ASR's reference rules. Encode these as 32 and 16 lowercase hexadecimal digits. Use the header's record ID for the session span and the call record's ID for a tool span.

OpenTelemetry IDs cannot be all zero. If a truncated digest is all zero, hash the same reference with `#1` appended, then `#2`, until nonzero. Keep one span per selected record so re-exporting does not create duplicate activity. Native trace context can be used when a documented producer mapping retains it under a reverse-DNS `_meta` key. An arbitrary native trace ID does not establish an OpenTelemetry parent.

Exclude copied records from the child's own spans and usage. A new model call over copied context belongs to the child. Never add `session_info.usage` totals to per-call totals. Do not assign a session total to a guessed model call.

## Content is optional

Leave prompts, replies, tool arguments and results out of telemetry by default. When content export is enabled, apply the user's data handling policy and preserve known truncation and loss information.

The core does not reconstruct the exact messages sent in a model request. Do not fill `gen_ai.input.messages` or `gen_ai.system_instructions` by collecting nearby session messages. A linked output message is an observed output, with whatever completeness the source provides.

Tool arguments and recorded results can use the convention's content attributes when their shapes and meanings match. Encrypted reasoning carries no content. Secrets are excluded before ASR is written and remain excluded from telemetry.

File changes, commits and annotations remain useful in ASR even when they produce no span. See [Records](../spec/records.md) and [Missing data](../spec/missing-data.md).
