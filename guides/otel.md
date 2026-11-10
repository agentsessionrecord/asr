---
title: "OpenTelemetry"
description: "Export recorded model and tool activity to OpenTelemetry GenAI spans."
---

An exporter can turn the model and tool calls in an Agent Session Record (ASR) session into spans that follow [OpenTelemetry's GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/). The attribute names below were checked on October 30, 2026 against the [GenAI registry](https://github.com/open-telemetry/semantic-conventions-genai/blob/72e0d0a097db3ba31ba3f33d0519401a044f6e23/model/gen-ai/registry.yaml), [GenAI spans](https://github.com/open-telemetry/semantic-conventions-genai/blob/72e0d0a097db3ba31ba3f33d0519401a044f6e23/model/gen-ai/spans.yaml), [OpenAI registry](https://github.com/open-telemetry/semantic-conventions-genai/blob/72e0d0a097db3ba31ba3f33d0519401a044f6e23/model/openai/registry.yaml), [user registry](https://github.com/open-telemetry/semantic-conventions/blob/debfc1c62dcaf49eece43e3ee1d56a92b837a7e2/model/user/registry.yaml) and [error registry](https://github.com/open-telemetry/semantic-conventions/blob/debfc1c62dcaf49eece43e3ee1d56a92b837a7e2/model/error/registry.yaml). The GenAI and user conventions are still under development, so name the revisions your exporter implements.

## Use recorded timing

A span needs a start and an end. Emit one only when the source establishes both, or a start and a duration. `ts` alone doesn't say whether it marks the start or the completion of an operation, so use the producer's documented meaning.

| ASR source | Span | Timing needed |
|---|---|---|
| Session header and latest `session_info` | `invoke_agent` | Recorded `startedAt` and `endedAt`. |
| `inference` | `chat`, or the recorded provider operation | A documented start `ts` and `durationMs`, or equivalent observed endpoints. |
| Uniquely paired `tool_call` and `tool_result` | `execute_tool` | Recorded call start and result completion, or recorded start and result `durationMs`. |
| A linked child session | `invoke_agent` for the child | The child's own recorded endpoints. |

Don't borrow time from neighboring records or fill a missing endpoint with the export time. The end of the file is not the end of the session, and a resumed session can have work after a recorded end, so check that the interval covers the exported activity.

If you use recorder receipt times, label them in the exporter's metadata as the observation interval, not measured agent execution time.

When a parent span can't be emitted, keep its timed children without it. A child's `parent.callId` can connect its session span to the delegating tool span, and `parentCallId` can connect a nested tool span to its enclosing tool. Leave unresolved links unresolved.

## Attributes

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

The two `agent_session.*` attributes are custom. The rest come from the semantic conventions.

ASR input counts already include cache reads and writes, and output counts already include reasoning, so export them without adding those subsets again. A derived inference ID is an ASR identity. Put it in `agent_session.record_id`, not `gen_ai.response.id`. A documented provider response ID kept in the agent's `_meta` can supply `gen_ai.response.id` instead.

Export recorded request settings without inventing defaults, and apply settings recorded for a turn to each of its established inference spans.

Include user attributes only when the export policy allows personal data, on the session span and any child spans that need that grouping. Don't guess whether `user.name` is a login or a full name. If you can't tell, leave it in ASR.

There is no provider-neutral service-tier attribute. Use the `openai.*` attributes only for OpenAI calls, and only when the source says whether the tier was requested or used for the response. Otherwise leave the tier in ASR.

Approval decisions, `asks`, `externalSandbox`, native agent policies, `user.source` and message triggers have no standard attributes, and configured `modelSettings` don't establish request attributes. Keep those facts in ASR. The [audit guide](audits.md) covers importing vendor decision events.

```jsonl
{"type":"inference","id":"response-7","ts":"2026-10-26T14:02:11Z","model":{"provider":"example","requested":"code-latest","id":"code-model-1"},"durationMs":850,"usage":{"inputTokens":1200,"cacheReadTokens":800,"outputTokens":120,"reasoningTokens":20}}
```

If this producer documents `ts` as the call start, the span ends 850 milliseconds later, with 1,200 input tokens and 120 output tokens. Without that timestamp contract, omit the span and export the usage through another reporting path.

A failed tool result or an inference with `error` can set the span status to error. Use a recorded error code for `error.type` where it fits. Don't infer a tool failure from a nonzero exit code when the source doesn't.

## Trace IDs and usage

For repeatable exports, derive the trace ID from the first 16 bytes of SHA-256 over the UTF-8 session reference without a fragment. Derive each span ID from the first 8 bytes of SHA-256 over the UTF-8 record reference `<sessionRef>#<recordId>`, with the record ID percent-encoded by ASR's reference rules. Write them as 32 and 16 lowercase hexadecimal digits. The session span uses the header's record ID, and a tool span uses the call record's ID.

OpenTelemetry IDs can't be all zero. If a truncated digest is all zero, hash the same reference with `#1` appended, then `#2`, until the result is nonzero. Keep one span per selected record so a re-export doesn't duplicate activity. Native trace context can be used when a documented producer mapping keeps it under a reverse-DNS `_meta` key. An arbitrary native trace ID doesn't establish an OpenTelemetry parent.

Exclude copied records from a child's own spans and usage. Never add `session_info.usage` totals to per-call totals or assign a session total to a guessed model call.

## Prompt and tool content

Leave prompts, replies, tool arguments and results out of telemetry by default. When content export is turned on, apply the user's data handling policy and keep known truncation and loss information.

ASR doesn't record the exact messages sent in a model request, so don't fill `gen_ai.input.messages` or `gen_ai.system_instructions` by collecting nearby session messages. Tool arguments and recorded results can use the convention's content attributes when their shapes and meanings match. Encrypted reasoning carries no content.
