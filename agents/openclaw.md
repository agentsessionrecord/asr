---
title: "OpenClaw"
description: "Converter notes for OpenClaw session storage."
---

These notes describe `openclaw`. Native details without a core field can use `_meta` under `ai.openclaw`.

## Logs and format

Use `producer.source: "openclaw-sqlite"`. Per-agent storage is `~/.openclaw/agents/<agentId>/agent/openclaw-agent.sqlite`. `session_nodes.entry_json` holds mutable session data. Tree-structured `transcript_events` keep `event_json` or losslessly compressed `event_zstd`, ordered by SQLite `seq`. Read a consistent snapshot. Legacy JSONL files can be migration or archive artifacts.

## Session identity

Use `session_windows.session_id` verbatim. The routing `session_key` is separate. Native UUIDs need no namespace in this mapping. The native session header supplies ID, time and `cwd`. Recorded window times can supply session endpoints. Export time and the last event do not establish an end.

## User and settings

`createdActor.type: human` with native `id` or `label` supplies `user.id` or `user.name`. Causal `delegatedBy` takes precedence over a legacy isolation owner. An agent creator does not inherit a human owner's identity as author. Recorded human sender identity can supply a message's `person` separately.

Recorded `permissionMode` supplies `agentSettings.approval`. A mutable current value belongs at the snapshot position and does not establish historical policy. `thinking_level_change.thinkingLevel` supplies configured `modelSettings.reasoningEffort`. These values do not supply `inference.settings`. Full effective policy, `asks` and an outer sandbox are not established by this mapping.

`custom` entries with `customType: openclaw.system-prompt` retain `data.tools`. Map each definition's `name`, `description` and `parameters` to `name`, `description` and `inputSchema`. Retained definitions remain offered even when execution is gated. Declare `tools` when coverage is partial.

## Record and call IDs

Native entry `id` identifies a message. Derive distinct IDs for split records. Assistant `toolCall.id` joins result `toolCallId` to form `callId`. Keep native ancestry and sequence, including abandoned work.

Assistant `responseId` identifies an inference. When it is absent, a persisted runtime model-call `turnId` can identify executable output's call. It differs from the harness run ID, which can supply ASR `turnId`. Split outputs and `supersedesEntryId` revisions share one inference, recorded once at completion. Native `model` is requested, while `responseModel` is served. Do not copy either into the other.

## Subagents and parents

Explicit window predecessor and fork fields establish `continues` or `fork`. Exact ancestor entry identities establish copies and the copied prefix. A copied inference retains `copiedFrom` even if its final revision falls after that prefix. New model calls over inherited context count as new work. Complete spawn-call and child-session joins are not established here.

## File-edit evidence

Map `read` to `read`, `write` and `edit` to `edit`, `exec`, `bash` and `bashExecution` to `execute`, `web_fetch` to `fetch`, and `web_search` to `search`. Other names leave `kind` absent.

Successful `changed` receipts from write/edit establish `applied`. A recorded `created` flag distinguishes add from modify when known. Preserve the recorded unified patch and verified full write contents as `patch` and `after.text`. Request text alone does not establish application. This mapping does not supply historical object IDs or full before-state contents.

## Commit evidence

A structured Git-action mapping and commit-output parser are not established here. Keep commands and output searchable and list `commits` in `missing`. A mention does not become a performed action.

## Usage arithmetic

When native `input` is present, inclusive `inputTokens = input + (cacheRead ?? 0) + (cacheWrite ?? 0)`. Emit supplied cache subsets separately. `output` is already inclusive. Preserve supplied reasoning counts and zeros. `usageReport.state: unavailable` excludes provisional usage. Retained revisions of a response do not multiply usage.

A recorded total cost is USD. Use `provider_reported` only for `provider-billed` and otherwise `harness_estimated`. Mutable context counters are not cumulative session totals.

## Missing data

Declare incomplete `approvals`, `agent_settings`, `tools`, `file_changes`, `commits`, `subagents` and `copies` as applicable. Missing call settings can use `inference_settings`. Mark shortened text with `truncated` and established history loss with a `gap`. Preserve native values beyond numeric precision as strings. Do not round them or infer missing boundaries.

## Capture coverage

| Area | Saved evidence and mapping |
|---|---|
| Messages | Native entries retain messages, compactions and revision ancestry. Incognito sessions have no durable transcript |
| Tool calls | Assistant `toolCall.id` joins `toolResult.toolCallId`, with recorded arguments and output |
| Offered tools | The `openclaw.system-prompt` checkpoint retains `data.tools` definitions |
| Approvals | Result `details.approvalId` can join a row in the separate `operator_approvals` store. `approvalReviews` and `approvalReviewOutcome` retain separate review evidence |
| Agent settings and asking | Current permission mode and recorded reasoning changes survive. Layered restrictions prevent a general `asks` mapping |
| External sandbox | `systemPromptReport.sandbox` describes a managed tool sandbox, not a boundary around the gateway. Keep it in `_meta` |
| Triggers | `createdVia: cron` supplies `scheduled`. Established webhook or channel provenance supplies `external`. Native IDs stay in `_meta` |
| Hooks | Hooks can block, rewrite or suppress saved calls and messages. Some decision receipts live in separate stores |
| Store changes | Session rows are mutable. Transcript rewrites retain `supersedesEntryId` chains |
| Omissions and pruning | Session maintenance can delete history. Terminal approvals have separate retention and row limits |

Map operator approvals by `status` first. `allowed` means `approved`, `denied` means `denied`, and `expired` or `cancelled` means `cancelled`. Ignore the default `deny` column for unanswered cases. `pending` and system/storage-corrupt rows do not establish decisions.

Use unique `approval_id` as record ID and `resolved_at_ms` as decision time. Keep native status, decision and resolver evidence. `resolver_id` can identify a device or channel, so it does not supply `person`. Set `by: user` only for a recorded human answer and `classifier` only for an explicit deciding review. `allow-once` supplies `once`. `allow-always` alone does not establish session or permanent scope.

An explicit post-decision result receipt places the approval immediately before that result. A receipt with `details.status: approval-pending` cannot position a later terminal decision. Keep unpositioned rows in `_meta` and declare `approvals`. Separate stores do not establish a common order by timestamp.

## Source versions

These mappings describe OpenClaw 2026.10.7. The [sample](https://github.com/agentsessionrecord/asr/tree/main/samples/openclaw) contains decoded native events, their session snapshot and the export. It is a synthetic run with recorded tool definitions and no tool invocation.

Identity and joins follow the [session accessor](https://github.com/openclaw/openclaw/blob/15e4d849d5f9a3559132454aeff90fe54781dee9/src/config/sessions/session-accessor.sqlite-session-row.ts), [creator provenance](https://github.com/openclaw/openclaw/blob/15e4d849d5f9a3559132454aeff90fe54781dee9/src/config/sessions/session-entry-provenance.ts) and [message types](https://github.com/openclaw/openclaw/blob/15e4d849d5f9a3559132454aeff90fe54781dee9/packages/llm-core/src/types.ts). Decisions follow the [approval fields](https://github.com/openclaw/openclaw/blob/15e4d849d5f9a3559132454aeff90fe54781dee9/src/gateway/operator-approval-store.fields.ts). These sources do not establish every field in every release.

## Worked example

This synthetic excerpt has a session header and a linked tool result. The assistant response ID establishes one inference. The example has no model identity or usage to supply.

```jsonl native
{"type":"session","id":"example-openclaw","cwd":"/work/app"}
{"type":"message","id":"entry-1","message":{"role":"assistant","responseId":"response-1","content":[{"type":"toolCall","id":"read-1","name":"read","arguments":{"path":"/work/app/hello.txt"}}]}}
{"type":"message","id":"entry-2","message":{"role":"toolResult","toolCallId":"read-1","isError":false,"content":[{"type":"text","text":"hello ASR\n"}]}}
```

The ASR stream keeps those identities and the recorded input and output:

```jsonl
{"type":"session","id":"header","formatVersion":"0.1","agent":{"name":"openclaw"},"sessionId":"example-openclaw","producer":{"name":"example-converter","version":"1.0","method":"converter","source":"openclaw-sqlite"},"cwd":"/work/app","missing":["model","usage","timestamps","approvals","agent_settings","tools","copies","subagents","file_changes","commits"]}
{"type":"inference","id":"response-1"}
{"type":"tool_call","id":"entry-1","inferenceId":"response-1","callId":"read-1","name":"read","kind":"read","requestedBy":"model","input":{"path":"/work/app/hello.txt"}}
{"type":"tool_result","id":"entry-2","callId":"read-1","status":"completed","content":[{"type":"text","text":"hello ASR\n"}]}
```

## Local native reference

The primary local integration is the standalone plugin under
`upstream/openclaw/plugin`. It uses public transcript and CLI APIs. The fuller
SQLite source patch remains a secondary reference. The transcript projection
does not provide complete history, all side stores or a tamper-evident chain.
