---
title: "OpenCode"
description: "Converter notes for OpenCode SQLite sessions."
---

OpenCode's SQLite sessions convert to Agent Session Record (ASR) with the [shared mappings](index.md#shared-mappings) and the rules below. Unmapped native fields can go in `_meta` under `ai.opencode`.

## Logs and format

Use `producer.source: "opencode-sqlite"`. The observed database is `~/.local/share/opencode/opencode.db`. Read the session, message and part tables, plus the sequenced `session_message` or `session_entry` tables when present, in one transaction that includes the WAL.

Use native sequence order. Legacy order is message `time_created`, then message ID, with parts ordered by part ID. A current snapshot does not show every state of a rewritten row.

## Session identity

Use `session.id` or `session_v2.id` verbatim, with no `namespace`. Paths and table names do not identify a session.

## User and settings

No native user identity, reasoning effort, output token limit, temperature or service tier is documented for these stored rows. In the v2 engine, `session_v2.agent` and assistant `agent` record the selected agent, and session `permission` stores overrides. Map the selection to `agentSettings.mode` and recorded overrides to `approval`, only at their established position. Neither includes the resolved policy or sandbox state.

An undated current row does not establish settings for past calls, and a message with the user role does not identify the person.

## Record and call IDs

Messages have `id`, parts have row IDs and tools have `callID`. A uniquely owned tool part supplies its call from `state.input` and its result from the final `state`. `completed` maps to `completed` and `error` to `failed`, while pending or running states do not establish success. Reused call IDs stay ambiguous.

A uniquely owned step or message usage report supports a derived inference ID. No native `turnId` is documented. Message `modelID` and `providerID` give the configured model and provider, so the model is requested, not served.

## Subagents and parents

A task tool's `metadata.sessionId` names its child. Record that link on the parent's call or result. It does not give the child a link back to its launching call.

`fork_session_id` identifies a fork where that exact field exists. `session.parent_id` alone does not distinguish delegation from other relationships, so keep it in `_meta` without choosing a parent kind.

## Tool kinds and file edits

Map `edit` and `write` to `kind: edit`, `read` to `read` and `bash` to `execute`. Other names leave `kind` absent unless documented.

An `edit` part's `state.input` has `filePath`, `oldString`, `newString` and optional `replaceAll`, and confirmed replacements can map to `edits`. A `write` input has `filePath` and full `content`. Inputs alone do not show the final bytes after formatting.

A completed edit's `state.metadata.diff` is recorded unified diff text, and `state.metadata.filediff` also has `file` and `patch`. Use one of them for `patch` without regenerating it. Write result metadata has `filepath` and `exists`, which tell a new file from an overwrite. Keep proposed content as input unless the result establishes what was written. Summary, checkpoint and unrelated patch fields do not establish edit endpoints.

## Commits

A `bash` part stores its command in `state.input.command` and its output in `state.output`. No structured Git result mapping is documented.

## Token usage and cost

Select one uniquely owned step report. Use message `tokens` only when they do not overlap that report. Otherwise keep the report in `_meta` and list `usage` as missing.

When `tokens.input` exists, `inputTokens = tokens.input + (tokens.cache?.read ?? 0) + (tokens.cache?.write ?? 0)`. When `tokens.output` exists, `outputTokens = tokens.output + (tokens.reasoning ?? 0)`. Supplied `cache.read`, `cache.write` and `reasoning` map to their ASR subsets. `tokens.total` combines input and output and is not the input count.

Recorded `cost` is a harness estimate in USD, so use `currency: USD` and `source: harness_estimated`. These inclusion rules depend on the backend in the described version. Do not add session totals to per-call figures.

## Missing data

List `copies` when inherited records cannot be detected, `model` when the served model is absent, `usage` when accounting overlaps cannot be resolved, `approvals` for incomplete decision coverage and `agent_settings` for missing effective policies. A `revert` pointing into a message part does not establish a rewind of the whole message, so keep it in `_meta`. A snapshot lacking history needs a `gap`.

## Approvals and agent settings

`permission.asked` and `permission.replied` are not saved. A stored `state.error` with `type: aborted` and `message: The user declined this tool call` establishes an `approval` with `decision: denied` and `by: user`, written before the result with no scope. Keep the source error in `native`.

Live replies are `once`, `always` and `reject`. `always` saves a project grant in the `permission` table, so an observed original grant has scope `always`. That table has no call or session attribution, so a converter cannot get past approvals from it. A live recorder writes an `approval` when the reply arrives, using `once` for a recorded one-time grant, `user` for an established answer and `policy` for established reuse. Do not reconstruct the policy effects `allow`, `deny` and `ask`, or hook evaluations, from the final tool status.

Effective rules, mutable project grants and hooks are not saved, so there is no general `asks` mapping.

For an outer sandbox, join `workspace_id` to the workspace provider and binding. Set `externalSandbox` only when separate recorded evidence shows a boundary around the agent process and its work, not just a tool execution environment. Otherwise keep the native evidence in `_meta`. The workspace reference alone does not establish `container`, `vm` or `remote`, and a latest-value workspace snapshot does not establish an earlier boundary.

## Triggers, hooks and storage

| Area | What the database keeps |
|---|---|
| Triggers | User-message `metadata.schedule` supplies `origin: scheduled`. Keep its `id`, `name`, `run`, `dueAt`, `late` and check data in `_meta` when present. No generic external-event field is documented |
| Hooks | Permission evaluation and before and after tool hooks can affect decisions and rewrite output. Hook identity and decisions are not documented as saved |
| Store changes | Sequenced v2 messages and parts, with session projections updated in place. Current v2 layouts need their own mapping beside the stored-row examples here. Raw event archiving is separate and off by default |
| Pruning | Session deletion and external tool-output expiry can remove evidence |

## Source versions

Storage mappings describe 1.18.18. Migration samples from 1.18.34 through 2.0.21 cover user messages, with synthetic assistant cases, and a 1.19.4 sample covers edits, shell tests, resume, forks and children. Tool fields follow the pinned [edit](https://github.com/anomalyco/opencode/blob/65c35977bd564e23c0e9cf124b3e3e3b9308e9e8/packages/opencode/src/tool/edit.ts) and [write](https://github.com/anomalyco/opencode/blob/65c35977bd564e23c0e9cf124b3e3e3b9308e9e8/packages/opencode/src/tool/write.ts) sources. Confirm each stored layout with a native sample.

Approval, trigger, hook and storage details describe the [v2 projector](https://github.com/anomalyco/opencode/blob/bf5d12c/packages/core/src/session/projector.ts), [permission implementation](https://github.com/anomalyco/opencode/blob/bf5d12c/packages/core/src/permission.ts) and [scheduler](https://github.com/anomalyco/opencode/blob/bf5d12c/packages/core/src/schedule.ts), checked October 30, 2026. These fields may not exist in the releases the worked example covers.

## Worked example

These synthetic rows show the `data` column decoded as JSON. The tool part belongs to the assistant message, whose usage is counted once with no duplicate step report. Its missing cache-write count stays absent.

```jsonl native
{"id":"example-opencode"}
{"id":"message-1","session_id":"example-opencode","data":{"role":"assistant","providerID":"example","modelID":"example-model","tokens":{"input":10,"output":5,"reasoning":3,"cache":{"read":2}}}}
{"id":"part-1","message_id":"message-1","session_id":"example-opencode","data":{"type":"tool","callID":"edit-1","tool":"edit","state":{"status":"completed","input":{"filePath":"/work/parser.py","oldString":"limit = int(value)\n","newString":"limit = int(value or \"0\")\n"},"output":"Edit applied.","metadata":{"diff":"--- a/parser.py\n+++ b/parser.py\n@@ -1 +1 @@\n-limit = int(value)\n+limit = int(value or \"0\")\n"}}}}
```

The ASR stream is:

```jsonl
{"type":"session","id":"header","formatVersion":"0.1","agent":{"name":"opencode"},"sessionId":"example-opencode","producer":{"name":"example-converter","version":"1.0","method":"converter","source":"opencode-sqlite"},"missing":["model","copies","timestamps","approvals","agent_settings"]}
{"type":"inference","id":"message-1:inference","model":{"provider":"example","requested":"example-model"},"usage":{"inputTokens":12,"cacheReadTokens":2,"outputTokens":8,"reasoningTokens":3}}
{"type":"tool_call","id":"part-1:call","inferenceId":"message-1:inference","callId":"edit-1","name":"edit","kind":"edit","input":{"filePath":"/work/parser.py","oldString":"limit = int(value)\n","newString":"limit = int(value or \"0\")\n"}}
{"type":"tool_result","id":"part-1:result","callId":"edit-1","status":"completed","content":[{"type":"text","text":"Edit applied."}]}
{"type":"file_change","id":"part-1:change","callId":"edit-1","path":"/work/parser.py","op":"modify","status":"applied","patch":"--- a/parser.py\n+++ b/parser.py\n@@ -1 +1 @@\n-limit = int(value)\n+limit = int(value or \"0\")\n"}
```

## Native export

The [OpenCode export patch](https://github.com/agentsessionrecord/asr/blob/main/upstream/opencode/README.md) adds `opencode session export SESSION_ID --format agent-session`. Set `OPENCODE_AGENT_SESSION_HISTORY=1` before recording, and restart a running server with that setting. Capture is partial and requires design approval.
