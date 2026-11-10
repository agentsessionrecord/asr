---
title: "Recording ACP sessions"
description: "A mapping from live ACP updates to completed ASR records."
---

A recorder can write an Agent Session Record (ASR) file from a live [Agent Client Protocol](https://agentclientprotocol.com/) connection. This mapping follows [ACP schema v2.0.0-alpha.9](https://github.com/agentclientprotocol/agent-client-protocol/releases/tag/schema-v2.0.0-alpha.9), published October 16, 2026, for wire protocol version 2, and uses the unstable schema at that revision for subagent and inter-session updates. The connection can show less than the agent's own logs, so declare what it misses as known losses.

## Start a stream

Use the ACP `sessionId` verbatim. Map the `initialize` response's `info.name` to a short name in the [agent list](../agents/index.md), or use a configured reverse-DNS name controlled by the agent's maintainer. A display name alone doesn't establish a domain. `info.version` supplies `agent.version`, and the `session/new` request supplies `cwd`. Its additional directories don't establish Git repositories, so write `repos` only from observed repository facts.

```jsonl
{"type":"session","id":"header","formatVersion":"0.1","agent":{"name":"com.example.coder","version":"1.0"},"sessionId":"acp-session-7","producer":{"name":"example-acp-recorder","version":"1.0","method":"recorder","source":"acp-2.0.0-alpha.9"},"cwd":"/work/parser","missing":["usage","model","timestamps","tool_output","approvals","agent_settings"]}
```

A recorder stamps live events with the time it received them, which isn't when the agent did the work, so it lists `timestamps` as missing. Items the agent replays during a resume get no event time unless the source supplies one.

## Fold updates into completed items

ACP upserts identify an entity by its stable ID. Follow the pinned schema's field rules. Usually an omitted field stays unchanged, `null` clears it and a value replaces it. On `session_message`, omitted or null sender and recipient IDs keep their known values. Arrays are replaced whole, chunks concatenate without added whitespace, full content replaces accumulated content, and `_meta` is patched key by key.

Buffer message chunks until the message is complete or the session goes idle, requires action, closes or disconnects, and keep a known interruption in `message.status`. Write a tool call once its request is complete and its result when the final outcome arrives. Streaming chunks never become records. When one ACP tool ID supplies both a call and a result, give them distinct record IDs and keep the unchanged `toolCallId` as their `callId`.

## Map the observed facts

| ACP item | ASR record or field |
|---|---|
| Accepted `session/prompt`, with its response `messageId` | `message`, `role: user`, `origin: prompt`. The prompt blocks become `content`. |
| `user_message`, `user_message_chunk` | The same message when `messageId` identifies the accepted prompt. |
| `agent_message`, `agent_message_chunk` | `message`, `role: assistant`. |
| `agent_thought`, `agent_thought_chunk` | A message containing a `reasoning` part. Leave `visibility` absent when ACP does not distinguish full text from a summary. |
| `tool_call_update` | `tool_call`, with `callId` from `toolCallId`, `input` from `rawInput`, and the recorded `name`, `kind` and `locations`. |
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

Mark a prompt `author: human` only when the recorder knows the client is relaying a person's input. A JSON-RPC error from `session/prompt` doesn't establish an accepted message.

Configuration options establish settings only as far as the agent documents what they mean, and the optional `category` is a display hint that doesn't by itself identify an approval policy. The connection doesn't guarantee the effective permission or sandbox settings or any outer boundary, so list `agent_settings` as missing when that evidence is known to be incomplete.

A completed edit call can establish an applied diff, and a failed one gives `failed`. A cancelled call leaves it unknown whether the diff was applied, a pending proposal stays `proposed`, and diff text alone doesn't establish success.

Prefer folded `content` blocks to `rawOutput`. When `content` is absent, text `rawOutput` can become text content, and structured raw output with no matching content shape goes under the recorder's reverse-DNS `_meta` key. Don't concatenate the two or call either one verified model input. Display-only terminal references stay vendor data.

## Permission decisions

In the pinned schema, `PermissionOption.kind` is on the request's option, and a selected response carries only `outcome: selected` and `optionId`. Keep each request with its `options` and join the selected ID to them. The call is `subject.toolCall.toolCallId` for a `tool_call` subject and `subject.toolCallId`, when known, for a `command` subject. Other subjects can have no call. Write the `approval` when the response arrives, with that call as `callId` and the receipt time as `ts`.

| ACP option kind or outcome | ASR `decision` | ASR `scope` |
|---|---|---|
| `allow_once` | `approved` | `once` |
| `allow_always` | `approved` | `always` if kept beyond the session, `session` if it ends with the session |
| `reject_once` | `denied` | `once` |
| `reject_always` | `denied` | `always` or `session` by the refusal's real lifetime |
| Outcome `cancelled` | `cancelled` | Absent |

The option kind is only a hint about lifetime, so omit `scope` when you can't tell whether a remembered answer outlives the session. Keep the selected option and outcome in `native`. An unknown option kind or outcome doesn't mean approval.

```jsonl
{"type":"approval","id":"permission-decision","callId":"edit-7","decision":"denied","scope":"once","native":{"option":{"optionId":"reject-7","name":"Reject once","kind":"reject_once"},"outcome":{"outcome":"selected","optionId":"reject-7"}}}
```

ACP doesn't say who or what decided, so set `by` and `person` only from another observed source. A second request for the same call is a separate record. A decision with no tool call omits `callId` and uses the recorded request title as `subject`, and a title naming a narrower request can supply `subject` on a linked decision. A `cancelled` decision doesn't establish the tool's final status. List `approvals` as missing when the connection hides decisions made by policy or other paths.

## Sessions and copies

Resuming with the same session ID continues the same stream, so don't append duplicates when the agent replays history. A fork gets a new header with `parent.kind: fork`, and replayed parent records get `copiedFrom` when ACP identity establishes the copy.

A subagent association can supply the child's `parent`, and the parent's `tool_call.subagent` when a tool call is identified. Don't invent a call to hold it. A received inter-session message can carry `author: agent` and `from` as a session reference, with other routing detail in `_meta`.

If an update changes an item after its line is written, produce a new export file or keep the update as vendor data. Don't rewrite lines in a live stream, and report any resulting loss.

## What the connection leaves unknown

ACP at this revision doesn't establish per-call model boundaries, so don't create `inference` records from reply boundaries. `usage_update.used` and `size` describe the context window, not accumulated token use, so list `usage` as missing. A model selection doesn't identify the served model. Plans, terminal lifecycle and intermediate statuses have no core records. Keep them as vendor data or list them as missing.

Never record server credentials, headers, environment secrets or secret answers to prompts. An ASR recording doesn't provide wire replay or session resume.
