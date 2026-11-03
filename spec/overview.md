---
title: Overview
description: A common record of agent work for search and blame.
sidebar:
  order: 1
---

Agent Session Record (ASR) is an open format for recording what an AI agent did in a session. It keeps prompts, replies, tool calls, file edits and commits in one shape across agents. Tools can index that work, search it and answer which session wrote a line and why.

ASR uses UTF-8 JSON Lines with the media type `application/vnd.agent-session+jsonl` and the file extension `.jsonl`. The format version is `0.1`.

## Terms

- A **source** is the native log, export, hook or live connection from which a fact comes.
- A **producer** is the software writing ASR. A **writer** is a producer claiming conformance.
- A **reader** displays, indexes or derives answers from ASR.
- A **stream** is the ordered records for one session.
- A **harness** is the program that runs the agent, such as Claude Code or Codex.
- An **inference** is one model call.

Examples with a session header show streams. Examples without one show record excerpts.

## Questions ASR answers

The core records support these questions, in priority order.

1. Which session wrote this line, from which prompt, with which model?
2. Which sessions made this commit or pull request, and what else did they do?
3. Which sessions read or changed this file?
4. Where does this text appear in prompts, replies or tool input and output across agents?
5. What happened in this session, in order?
6. What failed, and what happened next?
7. What did it cost, by model?
8. Which session started which subagent, with what task, and what came back?
9. Was the change kept, reverted or merged?

An answer cites recorded facts. The prompt and recorded explanation can help explain why a change happened. Missing evidence stays unknown. [Code links and blame](code.md) separates the session that edited a line from the session or person that committed it. [Annotations](annotations.md) add outcomes learned later.

## A small session

The first line identifies the session and the software that produced the file. Each following line records a completed item. This example uses a fictional agent.

```jsonl
{"type":"session","id":"header","formatVersion":"0.1","agent":{"name":"com.example.agent","version":"1.0"},"sessionId":"session-7","producer":{"name":"example-export","version":"1.0","method":"native"}}
{"type":"message","id":"prompt-1","role":"user","author":"human","origin":"prompt","content":[{"type":"text","text":"Explain the empty-input check."}]}
{"type":"message","id":"reply-1","role":"assistant","author":"model","phase":"final","content":[{"type":"text","text":"The check returns an empty list before parsing."}]}
```

The required fields are small. Times, model names, usage and repository details appear when the source records them. Their absence does not supply a default answer.

## How sessions get in

Most sessions reach ASR through a converter that reads an agent's native log files after the session. An agent can also offer an export command or write an ASR file next to its native log. A recorder can observe a live connection or hooks and record the items it sees.

The [agent list and converter notes](../agents/index.md) describe native formats and mappings. The [integration guide](../guides/integration.md) describes an export command convention, a discovery file and the `Agent-Session` commit trailer.

[Running ASR across a company](../guides/organizations.md) covers collection, user identity, shared storage, access and reporting.
[Using ASR for audits](../guides/audits.md) covers approval evidence, collection receipts and checks against independent systems.

## Records

The ten core record types keep work and decisions in file order.

| Record | What it keeps |
|---|---|
| [`session`](records.md#session) | Session identity, producer and starting facts |
| [`session_info`](records.md#session_info) | Settings, offered tools, totals and newly discovered losses |
| [`message`](records.md#message) | Prompts, replies and recorded instructions |
| [`tool_call`](records.md#tool_call) | A tool request and the arguments it received |
| [`tool_result`](records.md#tool_result) | A tool's recorded outcome and output |
| [`approval`](records.md#approval) | One decision, with its own identity and position |
| [`file_change`](records.md#file_change) | One changed file and its edit evidence |
| [`vcs`](records.md#vcs) | Version-control actions and pull request references |
| [`inference`](records.md#inference) | One recorded model call |
| [`gap`](records.md#gap) | A position where history is missing |

## Related formats and scope

ASR reuses MCP content and ACP tool shapes. Guides cover [ACP recording](../guides/acp.md), [Git AI notes](../guides/git-ai.md) and [OpenTelemetry export](../guides/otel.md).
It is an indexable log of work, without guarantees of exact model context, replay, resume, completeness, chat delivery, truth or safe sharing.

## Reading the specification

The eight pages in this specification are normative. Guides and agent notes add no requirements.

| Page | What it defines |
|---|---|
| [Overview](overview.md) | Purpose, scope and conventions |
| [Format](format.md) | Framing, order, identity, paths, content and extensions |
| [Records](records.md) | The ten core record types |
| [Sessions](sessions.md) | Parents, subagents and copied history |
| [Code links and blame](code.md) | Repository checks and attribution |
| [Missing data](missing-data.md) | Unknown values, gaps and safety |
| [Annotations](annotations.md) | Facts learned after a session |
| [Conformance](conformance.md) | Writer, reader and validator requirements |

The words MUST, MUST NOT, SHOULD, SHOULD NOT and MAY have the meanings in [BCP 14](https://www.rfc-editor.org/info/bcp14) when written in capitals. Numbered requirements identify obligations for implementations. Field tables define the shapes those requirements use. R means required, O means optional and C means required under the stated condition. Listed enum values are open to extension.
