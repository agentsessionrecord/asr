---
title: "OpenClaw"
description: "Converter notes for OpenClaw session storage."
---

OpenClaw's SQLite session storage converts to Agent Session Record (ASR) with the [shared mappings](index.md#shared-mappings) and the rules below. Unmapped native fields can go in `_meta` under `ai.openclaw`.

## Logs and format

Use `producer.source: "openclaw-sqlite"`. Each agent's database is `~/.openclaw/agents/<agentId>/agent/openclaw-agent.sqlite`. `session_nodes.entry_json` holds mutable session data. Tree-structured `transcript_events` keep `event_json` or the losslessly compressed `event_zstd`, ordered by SQLite `seq`. Read a consistent snapshot. Legacy JSONL files can be migration or archive artifacts.

## Session identity

Use `session_windows.session_id` verbatim, with no `namespace`. The routing `session_key` is separate. The native session header supplies the ID, time and `cwd`, and recorded window times can supply session start and end. Export time and the last event do not mark an end.

## User and settings

`createdActor.type: human` with a native `id` or `label` supplies `user.id` or `user.name`. Causal `delegatedBy` takes precedence over a legacy isolation owner. An agent creator does not take on a human owner's identity as author. A recorded human sender can supply a message's `person` separately.

Recorded `permissionMode` supplies `agentSettings.approval`. A mutable current value belongs at the snapshot position and does not establish past policy. `thinking_level_change.thinkingLevel` supplies the configured `modelSettings.reasoningEffort`. Neither supplies `inference.settings`, and the full effective policy is not established.

`custom` entries with `customType: openclaw.system-prompt` keep `data.tools`. Map each definition's `name`, `description` and `parameters` to `name`, `description` and `inputSchema`. A definition stays offered even when execution is gated. List `tools` in `missing` when coverage is partial.

## Record and call IDs

A native entry `id` identifies a message. Assistant `toolCall.id` joins result `toolCallId` to form `callId`.

Assistant `responseId` identifies an inference. Without it, a persisted runtime model-call `turnId` can identify the call behind executable output. That differs from the harness run ID, which can supply ASR `turnId`. Split outputs and `supersedesEntryId` revisions share one inference, recorded once at completion. Native `model` is the requested model and `responseModel` the served one. Do not copy either into the other.

## Subagents and parents

Explicit window predecessor and fork fields establish `continues` or `fork`. Exact ancestor entry IDs establish copies and the copied prefix. A copied inference keeps `copiedFrom` even when its final revision falls after that prefix. Complete joins between spawn calls and child sessions are not established.

## Tool kinds and file edits

Map `read` to `read`, `write` and `edit` to `edit`, `exec`, `bash` and `bashExecution` to `execute`, `web_fetch` to `fetch`, and `web_search` to `search`. Other names leave `kind` absent.

Successful `changed` receipts from write and edit establish `applied`, and a recorded `created` flag tells add from modify when known. Keep the recorded unified patch as `patch` and verified full write contents as `after.text`. This mapping gives no historical object IDs or full before-state contents.

## Commits

No structured Git action mapping or commit-output parser is established. Keep commands and output searchable and list `commits` in `missing`.

## Token usage and cost

When native `input` is present, `inputTokens = input + (cacheRead ?? 0) + (cacheWrite ?? 0)`, with supplied cache subsets emitted separately. `output` is already inclusive. Keep supplied reasoning counts and zeros. `usageReport.state: unavailable` excludes provisional usage, and kept revisions of a response do not multiply usage.

A recorded total cost is in USD. Use `provider_reported` only for `provider-billed`, and `harness_estimated` otherwise. Mutable context counters are not cumulative session totals.

## Missing data

Declare incomplete `approvals`, `agent_settings`, `tools`, `file_changes`, `commits`, `subagents` and `copies` as they apply. Missing call settings can use `inference_settings`. Mark shortened text with `truncated` and established history loss with a `gap`. Keep native values beyond numeric precision as strings, without rounding.

## Approvals and agent settings

Decisions live in the separate `operator_approvals` store, and a result's `details.approvalId` can join a row there. `approvalReviews` and `approvalReviewOutcome` keep separate review evidence. Map each row by `status` first, and ignore the default `deny` column for unanswered cases.

| `status` | `decision` |
|---|---|
| `allowed` | `approved` |
| `denied` | `denied` |
| `expired`, `cancelled` | `cancelled` |
| `pending`, system or storage-corrupt | No decision |

Use the unique `approval_id` as the record ID and `resolved_at_ms` as the decision time, and keep the native status, decision and resolver evidence. `resolver_id` can identify a device or channel, so it does not supply `person`. Set `by: user` only for a recorded human answer and `classifier` only for an explicit deciding review. `allow-once` supplies `once`, but `allow-always` alone does not establish session or permanent scope.

An explicit result receipt written after the decision places the approval just before that result. Its `details.approvalId` supplies the result's `approvalId` only when its store row produces that approval record. A pending receipt names its request before any decision, so it supplies no `approvalId`, and finished exec details can omit the ID. A store row whose `source_tool_call_id` matches the call does not show which decision the result followed, and a receipt with `details.status: approval-pending` cannot position a later terminal decision. Keep unpositioned rows in `_meta` and declare `approvals`. Timestamps in separate stores do not establish a common order.

Layered restrictions prevent a general `asks` mapping. `systemPromptReport.sandbox` describes a managed tool sandbox, not a boundary around the gateway, so keep it in `_meta`.

## Triggers, hooks and storage

| Area | What the database keeps |
|---|---|
| Triggers | `createdVia: cron` supplies `scheduled`. Established webhook or channel provenance supplies `external`. Native IDs stay in `_meta` |
| Hooks | Hooks can block, rewrite or suppress saved calls and messages. Some decision receipts live in separate stores |
| Store changes | Session rows are mutable. Native entries keep compactions and revision ancestry, and rewrites keep `supersedesEntryId` chains |
| Pruning | Session maintenance can delete history. Terminal approvals have separate retention and row limits. Incognito sessions have no durable transcript |

## Source versions

These mappings describe OpenClaw 2026.10.7. The [sample](https://github.com/agentsessionrecord/asr/tree/main/samples/openclaw) has decoded native events, their session snapshot and the export, from a synthetic run with recorded tool definitions and no tool calls. Identity and joins follow the [session accessor](https://github.com/openclaw/openclaw/blob/15e4d849d5f9a3559132454aeff90fe54781dee9/src/config/sessions/session-accessor.sqlite-session-row.ts), [creator provenance](https://github.com/openclaw/openclaw/blob/15e4d849d5f9a3559132454aeff90fe54781dee9/src/config/sessions/session-entry-provenance.ts) and [message types](https://github.com/openclaw/openclaw/blob/15e4d849d5f9a3559132454aeff90fe54781dee9/packages/llm-core/src/types.ts). Decisions follow the [approval fields](https://github.com/openclaw/openclaw/blob/15e4d849d5f9a3559132454aeff90fe54781dee9/src/gateway/operator-approval-store.fields.ts).

## Worked example

This synthetic excerpt has a session header and a linked tool result. The assistant response ID establishes one inference, and there is no model identity or usage to map.

```jsonl native
{"type":"session","id":"example-openclaw","cwd":"/work/app"}
{"type":"message","id":"entry-1","message":{"role":"assistant","responseId":"response-1","content":[{"type":"toolCall","id":"read-1","name":"read","arguments":{"path":"/work/app/hello.txt"}}]}}
{"type":"message","id":"entry-2","message":{"role":"toolResult","toolCallId":"read-1","isError":false,"content":[{"type":"text","text":"hello ASR\n"}]}}
```

The ASR stream is:

```jsonl
{"type":"session","id":"header","formatVersion":"0.1","agent":{"name":"openclaw"},"sessionId":"example-openclaw","producer":{"name":"example-converter","version":"1.0","method":"converter","source":"openclaw-sqlite"},"cwd":"/work/app","missing":["model","usage","timestamps","approvals","agent_settings","tools","copies","subagents","file_changes","commits"]}
{"type":"inference","id":"response-1"}
{"type":"tool_call","id":"entry-1","inferenceId":"response-1","callId":"read-1","name":"read","kind":"read","requestedBy":"model","input":{"path":"/work/app/hello.txt"}}
{"type":"tool_result","id":"entry-2","callId":"read-1","status":"completed","content":[{"type":"text","text":"hello ASR\n"}]}
```

## Native export

The [OpenClaw export plugin](https://github.com/agentsessionrecord/asr/blob/main/upstream/openclaw/README.md) is the main integration and uses public transcript and CLI APIs. A fuller SQLite source patch is a secondary reference. The transcript projection does not give complete history, all side stores or a tamper-evident chain.
