---
title: "OpenCode"
description: "Converter notes for OpenCode SQLite sessions."
---

These notes describe `opencode`. Native details without a core field can use `_meta` under `ai.opencode`.

## Logs and format

Use `producer.source: "opencode-sqlite"`. The observed database is `~/.local/share/opencode/opencode.db`. Read session, message and part tables, plus sequenced `session_message` or `session_entry` tables when available, in one transaction including the WAL.

Use native sequence order. Legacy order is message `time_created`, then message ID, with parts ordered by part ID. A current snapshot does not establish every state of a rewritten row.

## Session identity

Use `session.id` or `session_v2.id` verbatim. The described CLI IDs need no namespace. Paths and table names are not session identity.

## User and settings

Native user identity, reasoning effort, output token limit, temperature and service tier are not documented in these stored-row mappings. In the v2 engine, `session_v2.agent` and assistant `agent` record agent selection, while session `permission` stores overrides. Keep selection as `agentSettings.mode` and recorded overrides as `approval` only at their established position. They do not include the resolved policy or sandbox state.

An undated current row does not establish settings for all past calls. Leave unknown settings absent. A separately observed Git or configured exporter identity can supply `user` with its source. A message with a user role does not identify that person.

## Record and call IDs

Messages have `id`, parts have row IDs, and tools have `callID`. Keep those native identities when deriving separate records. A uniquely owned tool part supplies its call from `state.input` and its result from the final `state`. `completed` maps to `completed`, `error` to `failed`, and pending or running states do not establish success. Reused call IDs stay ambiguous.

A uniquely owned step or message usage report supports a derived inference ID. Native `turnId` is not documented. Message `modelID` and `providerID` identify configured model and provider. The model stays requested, not served.

## Subagents and parents

A task tool's `metadata.sessionId` names its child. Map that to the parent's call or result. It does not identify the child's inverse launching call.

`fork_session_id` identifies a fork where that exact field exists. `session.parent_id` alone does not distinguish delegation from other relationships. Keep it in `_meta` without choosing a parent kind. Matching IDs do not establish copied history.

## File-edit evidence

Map `edit` and `write` to `kind: edit`, `read` to `read`, and `bash` to `execute`. Other names need a documented map or keep `kind` absent.

An `edit` part's `state.input` contains `filePath`, `oldString`, `newString` and optional `replaceAll`. Confirmed replacements can map to `edits`. A `write` input has `filePath` and full `content`. Inputs alone do not establish application or the final bytes after formatting.

A completed edit's `state.metadata.diff` is recorded unified diff text. `state.metadata.filediff` also has `file` and `patch`. Use one recorded representation for `patch`, without regenerating it. Write result metadata has `filepath` and `exists`, distinguishing a new file from an overwrite. Retain proposed content as input unless the result establishes the written content. Summary, checkpoint and unrelated patch fields do not establish edit endpoints.

## Commit evidence

A `bash` part stores its command in `state.input.command`, with result text in `state.output`. When a completed call actually runs `git commit`, output `[branch short-id] subject` supports a `vcs` record with `parsed_output`, `commitPrefix` and `subject`. Parent counts require separate evidence. Do not turn a stored commit mention or history query into a performed action. A dedicated structured Git-result mapping is not documented.

## Usage arithmetic

Select one uniquely owned step report. Use message `tokens` only when it does not overlap that step's report. Otherwise retain the report in `_meta` and list `usage` missing.

When `tokens.input` exists, `inputTokens = tokens.input + (tokens.cache?.read ?? 0) + (tokens.cache?.write ?? 0)`. When `tokens.output` exists, `outputTokens = tokens.output + (tokens.reasoning ?? 0)`. Map supplied `cache.read`, `cache.write` and `reasoning` to their ASR subsets. Leave absent subset fields absent. `tokens.total` combines input and output and is not the input count. Lost counts remain unknown.

Recorded `cost` is harness-estimated USD. Use `currency: USD` and `source: harness_estimated`. These inclusion rules depend on the backend in the described version. Do not add session totals to per-call figures.

## Missing data

List `copies` when inherited records cannot be detected, `model` when the served model is absent and `usage` when accounting overlaps cannot be resolved. Declare unsupported edit or commit mappings.

A `revert` pointing into a message part does not establish a historical rewind of the whole message. Retain it in `_meta`. A snapshot lacking history needs a gap. Keep available abandoned work in native order.

## Capture coverage

| Area | Saved evidence and mapping |
|---|---|
| Messages | Sequenced v2 messages and parts, with mutable session projections |
| Tool calls | Native call IDs, input, final output and errors. Current v2 layouts need their own mapping beside the stored-row examples above |
| Approvals | `permission.asked` and `permission.replied` are ephemeral. A stored `state.error` with `type: aborted` and `message: The user declined this tool call` establishes an `approval` with `decision: denied` and `by: user`, before the result. Scope is not established. Keep the source error in `native`. Successful tools do not establish approval |
| Agent settings and asking | Agent selection and permission overrides are saved, but effective rules, mutable project grants and hooks are not snapshotted. No general `asks` mapping is established |
| External sandbox | Join `workspace_id` to the workspace provider and binding. Set `externalSandbox` only when separate recorded evidence establishes a boundary around the agent process and its work. A tool execution environment alone does not establish it. Preserve the native evidence in `_meta` when that condition is unknown. The reference alone does not establish `container`, `vm` or `remote` |
| Triggers | User-message `metadata.schedule` supplies `origin: scheduled`. Keep its `id`, `name`, `run`, `dueAt`, `late` and check data in `_meta` when present. A generic external-event discriminator is not documented |
| Hooks | Permission evaluation and before/after tool hooks can affect decisions and rewrite output. Dedicated hook identity and decision persistence are not documented |
| Store changes | SQLite projections are updated in place. Raw event archiving is separate and defaults off |
| Omissions and pruning | List `approvals` for incomplete decision coverage and `agent_settings` for missing effective policies. Session deletion and external tool-output expiry can remove evidence |

Live replies are `once`, `always` and `reject`. `always` persists project grants in the `permission` table, so an observed original grant has scope `always`. That table has no call/session attribution and cannot supply historical approvals to a converter. A live recorder writes an `approval` when the reply arrives. It can use `once` for a recorded one-time grant, `user` for an established answer and `policy` for established reuse. Policy effects `allow`, `deny`, `ask` and hook evaluations are not reconstructed from the final tool status.

A latest-value workspace snapshot does not establish an earlier outer boundary. A recorded permission mode belongs in `agentSettings.approval`, while a working mode or selected agent belongs in `mode`.

## Source versions

Storage mappings describe 1.18.18. Migration samples from 1.18.34 through 2.0.21 cover user messages, with synthetic assistant cases. A 1.19.4 sample covers edits, shell tests, resume, forks and children. Tool fields follow the pinned [edit](https://github.com/anomalyco/opencode/blob/65c35977bd564e23c0e9cf124b3e3e3b9308e9e8/packages/opencode/src/tool/edit.ts) and [write](https://github.com/anomalyco/opencode/blob/65c35977bd564e23c0e9cf124b3e3e3b9308e9e8/packages/opencode/src/tool/write.ts) sources. Confirm each stored layout with a native sample.

Capture details describe the [v2 projector](https://github.com/anomalyco/opencode/blob/bf5d12c/packages/core/src/session/projector.ts), [permission implementation](https://github.com/anomalyco/opencode/blob/bf5d12c/packages/core/src/permission.ts) and [scheduler](https://github.com/anomalyco/opencode/blob/bf5d12c/packages/core/src/schedule.ts), checked October 30, 2026. Do not assume that these fields exist in the releases covered by the worked example.

## Worked example

These synthetic SQLite row excerpts show the `data` columns decoded as JSON. The tool part belongs to the assistant message. That message's usage is selected once, without a duplicate step report. Its missing cache-write count stays absent.

```jsonl native
{"id":"example-opencode"}
{"id":"message-1","session_id":"example-opencode","data":{"role":"assistant","providerID":"example","modelID":"example-model","tokens":{"input":10,"output":5,"reasoning":3,"cache":{"read":2}}}}
{"id":"part-1","message_id":"message-1","session_id":"example-opencode","data":{"type":"tool","callID":"edit-1","tool":"edit","state":{"status":"completed","input":{"filePath":"/work/parser.py","oldString":"limit = int(value)\n","newString":"limit = int(value or \"0\")\n"},"output":"Edit applied.","metadata":{"diff":"--- a/parser.py\n+++ b/parser.py\n@@ -1 +1 @@\n-limit = int(value)\n+limit = int(value or \"0\")\n"}}}}
```

The ASR stream declares missing model identity, copies, timestamps, approvals and agent settings:

```jsonl
{"type":"session","id":"header","formatVersion":"0.1","agent":{"name":"opencode"},"sessionId":"example-opencode","producer":{"name":"example-converter","version":"1.0","method":"converter","source":"opencode-sqlite"},"missing":["model","copies","timestamps","approvals","agent_settings"]}
{"type":"inference","id":"message-1:inference","model":{"provider":"example","requested":"example-model"},"usage":{"inputTokens":12,"cacheReadTokens":2,"outputTokens":8,"reasoningTokens":3}}
{"type":"tool_call","id":"part-1:call","inferenceId":"message-1:inference","callId":"edit-1","name":"edit","kind":"edit","input":{"filePath":"/work/parser.py","oldString":"limit = int(value)\n","newString":"limit = int(value or \"0\")\n"}}
{"type":"tool_result","id":"part-1:result","callId":"edit-1","status":"completed","content":[{"type":"text","text":"Edit applied."}]}
{"type":"file_change","id":"part-1:change","callId":"edit-1","path":"/work/parser.py","op":"modify","status":"applied","patch":"--- a/parser.py\n+++ b/parser.py\n@@ -1 +1 @@\n-limit = int(value)\n+limit = int(value or \"0\")\n"}
```

## Local native reference

The local native reference uses
`opencode session export SESSION_ID --format agent-session`.
Enable `OPENCODE_AGENT_SESSION_HISTORY=1` before recording and restart an
existing server with that setting. Capture is partial and requires design approval.
