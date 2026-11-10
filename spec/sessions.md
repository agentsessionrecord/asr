---
title: Sessions
description: Parents, subagents, continuation and copied history.
sidebar:
  order: 4
---

A subagent, fork or continuation is a separate session that can name the session it came from. Readers use these links to follow delegated work without counting copied history twice.

## Parent

The optional `session.parent` object links a session to its parent or predecessor.

| Field | Req | Meaning |
|---|---|---|
| `session` | R | Session reference of the parent or predecessor |
| `kind` | R | `subagent`, `fork`, `continues` |
| `callId` | O | Parent's call that started a subagent |
| `record` | O | Last shared record ID in the parent for a fork |
| `role` | O | Subagent role or type, verbatim |
| `copiedThrough` | O | Last record ID in this file's copied prefix |

`subagent` means the parent started this session. `fork` means this session branched from the parent's history. `continues` means it picks up where a predecessor stopped under a different session ID. Examples are a resume that gets a new ID, compaction into a new session and a daily restart.

**ASR-040** A `parent` object MUST have `session` and `kind` and use these field shapes. A `copiedFrom` object MUST have `session`, `record` or both, using a session reference and source record ID respectively.

`parent.record` points into the parent's file, and `parent.copiedThrough` points into this file. A fork can name the last shared record without copying that history into its own file.

## Copies and credit

**ASR-041** `parent.copiedThrough` MUST name a record after the header in this file. Every record after the header up to and including that record MUST be treated as copied from the parent.

The prefix ends by position in the file, not by ID or timestamp. A record outside the prefix can carry `copiedFrom` to mark it as a copy. Its source session or record can be unknown, but not both. A copy stays a copy when its source is unavailable.

**ASR-042** Producers MUST assert `parent`, `copiedFrom` and `copiedThrough` only from a native field or storage structure, never from similar text, timing or shared folders. A producer that cannot detect copies MUST list `copies` in `missing`.

**ASR-043** Readers MUST count a record as this session's own work for blame, cost and edit counts unless it carries `copiedFrom` or falls within `copiedThrough`. They MUST exclude those copies from this session's credit and count new model calls over inherited context as the child's work.

An inference that appears in several native revisions of the same session is recorded once.

Copied records still appear in search and display. If `missing` lists `copies`, some copies may be unmarked, but readers apply the same credit rule.

## Subagents

The parent records delegation in `tool_call.subagent`. Its optional `session`, `role` and `description` fields name the child session, its role and its task. If the child session is only known at completion, `tool_result.subagent` can name it. The child's `parent` can name the parent and the `callId` that started it.

**ASR-044** Readers MUST combine available parent-side and child-side links to the same subagent relationship. Either side alone MUST be accepted, and an unavailable related session file MUST remain an unresolved reference rather than an error.

In this example a parent delegates a review. The tool result holds the child's answer.

```jsonl
{"type":"session","id":"header","formatVersion":"0.1","agent":{"name":"com.example.agent"},"sessionId":"parent-7","producer":{"name":"example-export","version":"1.0","method":"native"}}
{"type":"message","id":"prompt-1","role":"user","author":"human","origin":"prompt","content":[{"type":"text","text":"Review the empty-input handling."}]}
{"type":"tool_call","id":"spawn-record","callId":"spawn-1","name":"start_agent","subagent":{"session":"com.example.agent:child-7","role":"reviewer","description":"Check empty-input handling."}}
{"type":"tool_result","id":"spawn-result","callId":"spawn-1","status":"completed","content":[{"type":"text","text":"The empty-input check is present."}],"subagent":{"session":"com.example.agent:child-7"}}
```

The child starts with a copied prompt. Its own model call and reply follow, and that call's usage counts toward the child.

```jsonl
{"type":"session","id":"header","formatVersion":"0.1","agent":{"name":"com.example.agent"},"sessionId":"child-7","producer":{"name":"example-export","version":"1.0","method":"native"},"parent":{"session":"com.example.agent:parent-7","kind":"subagent","callId":"spawn-1","role":"reviewer","copiedThrough":"inherited-prompt"}}
{"type":"message","id":"inherited-prompt","role":"user","author":"human","origin":"prompt","content":[{"type":"text","text":"Review the empty-input handling."}]}
{"type":"inference","id":"child-call-1","model":{"requested":"review-model"},"usage":{"inputTokens":80,"outputTokens":12}}
{"type":"message","id":"child-reply","inferenceId":"child-call-1","role":"assistant","author":"model","phase":"final","content":[{"type":"text","text":"The empty-input check is present."}]}
```

If the parent also stores a copy of the child's reply as a separate message, that message carries `copiedFrom`. The parent's call that started the child is still the parent's own work.

## Continuation and native trees

**ASR-045** A resume with the same native session identity MUST remain the same session. Producers MUST write tree-shaped native history in native order and retain work from rewound or abandoned branches as ordinary records. Readers MUST include their recorded work in search, cost and blame under the same credit rules.

An edit on an abandoned branch can still reach a commit, and a model call there still used tokens. The stream keeps those records, but it does not rebuild the exact conversation tree or the model's full context.

A continuation with a new native ID uses `parent.kind: "continues"` when the source records the relationship. A compaction summary uses a [message](records.md#message), followed by a gap when earlier history is lost.
