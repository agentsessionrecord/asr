---
title: "Recording ACP sessions"
description: "A mapping from live ACP updates to completed ASR records."
---

This guide describes recording a live [Agent Client Protocol](https://agentclientprotocol.com/) connection as ASR. It covers [ACP schema v2.0.0-alpha.9](https://github.com/agentclientprotocol/agent-client-protocol/releases/tag/schema-v2.0.0-alpha.9), published October 16, 2026, for wire protocol version 2. Subagent and inter-session updates use the unstable schema at that revision. This guide adds no requirements.

ACP carries the interaction between an editor and an agent. A recorder sees that connection, which may expose less than the agent's own logs. It records what it observes and names the losses.

## Start a stream

Use the ACP `sessionId` verbatim. Map `initialize` response `info.name` to a short name in the [agent list](../agents/index.md), or use a configured reverse-DNS name controlled by the agent's maintainer. An arbitrary display name does not establish a domain. `info.version` supplies `agent.version`.

The `session/new` request supplies `cwd`. Additional directories do not establish Git repositories. Write `repos` only when repository facts are observed.

Set `producer.method` to `recorder`. Use a string naming the schema in `producer.source`, as in this illustrative header:

```jsonl
{"type":"session","id":"header","formatVersion":"0.1","agent":{"name":"com.example.coder","version":"1.0"},"sessionId":"acp-session-7","producer":{"name":"example-acp-recorder","version":"1.0","method":"recorder","source":"acp-2.0.0-alpha.9"},"cwd":"/work/parser","missing":["usage","model","timestamps","tool_output","approvals","agent_settings"]}
```

A recorder uses receipt time for live events. That is not the time the agent performed the work, so list the missing source timestamps. Omit event times on historical items replayed during resume unless source times are available.

## Fold updates into completed items

ACP upserts identify an entity by its stable ID. Apply the pinned schema's field rules. Usually an omitted field stays unchanged, `null` clears it, and a value replaces it. On `session_message`, omitted or null sender and recipient IDs retain known values. Arrays are replaced as a whole. Chunks concatenate without inserted whitespace. Full content replaces accumulated content. Patch `_meta` key by key.

Buffer message chunks until the message is complete or the session becomes idle, requires action, closes or disconnects. Preserve a known interruption in `message.status`. A tool call can be written once its request is complete, with its result written when the final outcome arrives. Do not emit streaming chunks as ASR records.

Keep completed items in observed order. Derive distinct record IDs when one ACP tool ID supplies both a call and a result. The unchanged native `toolCallId` remains their `callId`.

## Map the observed facts

| ACP item | ASR record or field |
|---|---|
| Accepted `session/prompt`, with its response `messageId` | `message`, `role: user`, `origin: prompt`. The prompt blocks become `content`. |
| `user_message`, `user_message_chunk` | The same message when `messageId` identifies the accepted prompt. |
| `agent_message`, `agent_message_chunk` | `message`, `role: assistant`. |
| `agent_thought`, `agent_thought_chunk` | A message containing a `reasoning` part. Leave `visibility` absent when ACP does not distinguish full text from a summary. |
| `tool_call_update` | `tool_call`, with `callId` from `toolCallId`, and recorded `name`, `kind`, `rawInput` and `locations`. `rawInput` becomes `input`. |
| Final tool status | `tool_result` with `completed`, `failed` or `cancelled`. Unresolved status stays `unknown`. |
| `session/request_permission` and its response | An `approval` record when the response arrives, using the request's options and the mapping below. |
| Tool `content`, `tool_call_content_chunk` | Fold content updates. Unwrap `type: content` blocks into `tool_result.content`. ACP does not establish that this is what reached the model. |
| Tool `diff.changes` | One `file_change` per file, using `operation` as `op`, and recorded `path` and `oldPath`. Keep a recorded per-file unified patch as `patch`. |
| `session_info_update.title` | `session_info.title`. |
| Initial `configOptions`, `config_option_update` and successful `session/set_config_option` responses | `session_info.agentSettings.mode` for a documented working-mode selector, or `approval` for a documented permission selector, using its observed `currentValue` verbatim. |
| `usage_update.cost` | `session_info.cost` with the recorded amount and currency. |
| `compaction_update`, `compaction_summary_chunk` | Fold by `compactionId` into a summary message with `origin: compaction`, followed by a `gap` if history was lost. |
| `subagent_update` | Its `sessionId` identifies the child. Record a child's `parent` when its session is observed. No tool-call ID is supplied by this update. |
| `session_message`, `session_message_chunk` | On the receiving session, `message` with `role: user`, `author: agent`, `origin: injected`, and `from` when `senderSessionId` is known. |
| `notice` | `message`, `author: harness`, `origin: notice`. |
| Successful `session/close` | `session_info.endedAt` using the recorder's receipt time. |

Only mark a prompt `author: human` when the recorder knows the client is relaying a person's input. A JSON-RPC error from `session/prompt` does not establish an accepted message.

Configuration options can establish settings when the agent documents their meaning. The optional `category` is a display hint, so it does not alone identify an approval policy. Record each established value at the position observed. The connection does not guarantee effective permission or sandbox settings or an outer boundary. List `agent_settings` when that evidence is known to be incomplete, as in the example header.

A completed edit call can establish an applied diff. A failed call supplies `failed`, a cancelled call leaves application unknown, and a pending proposal stays `proposed`. Diff text by itself does not establish success. Preserve paths inside patches and input exactly.

Prefer folded `content` blocks to `rawOutput` when both exist. If `content` is absent, text `rawOutput` can become text content. Keep structured raw output without a matching content shape under the recorder's reverse-DNS `_meta` key. Do not concatenate the two representations or call either verified model input. Keep display-only terminal references as vendor data.

## Permission decisions

Keep each permission request and its `options`. In the pinned schema, `PermissionOption.kind` is on a request option. A selected response carries `outcome: selected` and `optionId`, so the response alone does not establish approval or denial. Join the selected ID to that request's option. For a `tool_call` subject, `subject.toolCall.toolCallId` identifies the call. For a `command` subject, `subject.toolCallId` identifies it when known. Other subjects can have no call. Write an `approval` record when the response arrives, using the identified call as `callId` and receipt time as `ts`.

| ACP option kind or outcome | ASR `decision` | ASR `scope` |
|---|---|---|
| `allow_once` | `approved` | `once` |
| `allow_always` | `approved` | `always` if kept beyond the session, `session` if it ends with the session |
| `reject_once` | `denied` | `once` |
| `reject_always` | `denied` | `always` or `session` by the refusal's real lifetime |
| Outcome `cancelled` | `cancelled` | Absent |

ACP's option kind is a hint. It does not establish whether a remembered answer survives the session. Omit `scope` when its real lifetime is unknown. Preserve the selected option and outcome in `native`. An unknown option kind or outcome does not mean approval.

ACP does not identify who or what decided. Set `by` and `person` only when another observed source establishes them. Reuse of a grant is `by: policy`, even when a person created it. Keep multiple decisions as separate records in source order, including a second request for the same call. A decision with no tool call omits `callId` and uses the recorded request title as `subject`. A title naming a narrower request can also supply `subject` on a linked decision.

```jsonl
{"type":"approval","id":"permission-decision","callId":"edit-7","decision":"denied","scope":"once","native":{"option":{"optionId":"reject-7","name":"Reject once","kind":"reject_once"},"outcome":{"outcome":"selected","optionId":"reject-7"}}}
```

The excerpt keeps the recorded denial without guessing an answerer or a tool outcome. A source that reports only a cancelled request supplies `decision: cancelled`, which does not by itself establish a tool's final status. List `approvals` in `missing` when the connection omits decisions made by policy or other paths. Declare a newly discovered loss in the next `session_info.missing`.

## Sessions and copies

Resume with the same session ID continues the same stream. Do not append duplicate entities when the agent replays history. A fork creates a new header with `parent.kind: fork`. Mark replayed parent records with `copiedFrom` when ACP identity establishes the copy. Use `copiedThrough` only for an established initial copied prefix.

An ACP subagent association can supply the child's `parent` and the parent's `tool_call.subagent` when a tool call is identified. Do not invent a call to hold an association. A received inter-session message can carry `author: agent` and `from` as a session reference. Keep unsupported routing detail in `_meta`.

If an update changes an item after its complete ASR line is written, produce a new export file or retain the update as vendor data. Do not rewrite a complete line in a live stream. Report any resulting loss.

## What the connection leaves unknown

ACP at this revision does not establish per-call model boundaries. Do not create `inference` records from reply boundaries. `usage_update.used` and `size` describe the context window, not accumulated token use. Keep them in `_meta` if useful, and list `usage` in `missing`.

Model selection alone does not identify a served model. Tool display content does not establish model-facing output. Plans, terminal lifecycle and intermediate statuses have no dedicated core records. Retain useful detail as vendor data or name the omitted category in `missing`.

Do not record server credentials, headers, environment secrets or secret prompt answers. Recording ASR does not provide wire replay or session resume. See [Missing data](../spec/missing-data.md) and [Records](../spec/records.md).
