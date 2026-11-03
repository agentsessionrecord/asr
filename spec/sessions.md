---
title: Sessions
description: Parents, subagents, continuation and copied history.
sidebar:
  order: 4
---

A session keeps its native identity. A related session has its own stream and can name its parent or predecessor. These links let a reader follow delegated work and inherited context without counting copied work twice.

## Parent

The optional `session.parent` object describes one relationship.

| Field | Req | Meaning |
|---|---|---|
| `session` | R | Session reference of the parent or predecessor |
| `kind` | R | `subagent`, `fork`, `continues` |
| `callId` | O | Parent's call that started a subagent |
| `record` | O | Last shared record ID in the parent for a fork |
| `role` | O | Subagent role or type, verbatim |
| `copiedThrough` | O | Last record ID in this file's copied prefix |

`subagent` means the parent started this session. `fork` means this session branched from the parent's history. `continues` means it picks up where a predecessor stopped under a different session ID. That includes a resume with a new ID, compaction into a new session or a daily restart.

**ASR-040** A `parent` object MUST have `session` and `kind` and use these field shapes. A `copiedFrom` object MUST have `session`, `record` or both, using a session reference and source record ID respectively.

`parent.record` points into the parent's file. `parent.copiedThrough` points into this file. They answer different questions. A fork can link to shared history without including copies of that history in its own stream.

## Copies and credit

**ASR-041** `parent.copiedThrough` MUST name a record after the header in this file. Every record after the header up to and including that record MUST be treated as copied from the parent.

The boundary follows file order. It does not compare IDs or timestamps. A record outside the prefix can carry `copiedFrom` to mark an individual copy. The source session or record can be unknown, but at least one must be named. An unavailable source does not make the copy original.

**ASR-042** Producers MUST assert `parent`, `copiedFrom` and `copiedThrough` only from a native field or storage structure, never from similar text, timing or shared folders. A producer that cannot detect copies MUST list `copies` in `missing`.

**ASR-043** Readers MUST count a record as this session's own work for blame, cost and edit counts unless it carries `copiedFrom` or falls within `copiedThrough`. They MUST exclude those copies from this session's credit and count new model calls over inherited context as the child's work.

An inference retained in several native revisions of the same session is recorded once, and a copied inference carries `copiedFrom` and gets no credit in the copying session.

Copies remain useful for search and display. The credit rule does not erase them. A missing `copies` capability reports a limit on the producer's knowledge. It does not introduce another originality state or change the rule.

## Subagents

The parent records delegation through `tool_call.subagent`. Its optional `session` names the child, `role` records its role, and `description` records the task description. A `tool_result.subagent` can supply the child session when it becomes known at completion. The child's `parent` can name the parent and its starting `callId`.

**ASR-044** Readers MUST combine available parent-side and child-side links to the same subagent relationship. Either side alone MUST be accepted, and an unavailable related session file MUST remain an unresolved reference rather than an error.

Here is a parent that delegates a review. The result keeps what came back.

```jsonl
{"type":"session","id":"header","formatVersion":"0.1","agent":{"name":"com.example.agent"},"sessionId":"parent-7","producer":{"name":"example-export","version":"1.0","method":"native"}}
{"type":"message","id":"prompt-1","role":"user","author":"human","origin":"prompt","content":[{"type":"text","text":"Review the empty-input handling."}]}
{"type":"tool_call","id":"spawn-record","callId":"spawn-1","name":"start_agent","subagent":{"session":"com.example.agent:child-7","role":"reviewer","description":"Check empty-input handling."}}
{"type":"tool_result","id":"spawn-result","callId":"spawn-1","status":"completed","content":[{"type":"text","text":"The empty-input check is present."}],"subagent":{"session":"com.example.agent:child-7"}}
```

The child contains one copied prompt, followed by its own model call and reply. The child incurs the new call's usage even though the call reads inherited context.

```jsonl
{"type":"session","id":"header","formatVersion":"0.1","agent":{"name":"com.example.agent"},"sessionId":"child-7","producer":{"name":"example-export","version":"1.0","method":"native"},"parent":{"session":"com.example.agent:parent-7","kind":"subagent","callId":"spawn-1","role":"reviewer","copiedThrough":"inherited-prompt"}}
{"type":"message","id":"inherited-prompt","role":"user","author":"human","origin":"prompt","content":[{"type":"text","text":"Review the empty-input handling."}]}
{"type":"inference","id":"child-call-1","model":{"requested":"review-model"},"usage":{"inputTokens":80,"outputTokens":12}}
{"type":"message","id":"child-reply","inferenceId":"child-call-1","role":"assistant","author":"model","phase":"final","content":[{"type":"text","text":"The empty-input check is present."}]}
```

If the parent also stores the child's reply as a separate message copied from the child, that message uses `copiedFrom`. The parent's own request to start the child remains its own work.

## Continuation and native trees

**ASR-045** A resume with the same native session identity MUST remain the same session. Producers MUST write tree-shaped native history in native order and retain work from rewound or abandoned branches as ordinary records. Readers MUST include their recorded work in search, cost and blame under the same credit rules.

An abandoned edit can still have text that survives in a commit. A model call on an abandoned branch still incurred usage. ASR records that work without reconstructing an exact conversation tree or the model's full context.

A continuation with a new native ID uses `parent.kind: "continues"` when the source records the relationship. A compaction summary uses a [message](records.md#message) and a following gap when earlier history is lost.
