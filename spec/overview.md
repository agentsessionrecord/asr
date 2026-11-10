---
title: Overview
description: Terms, scope, record types and conventions.
sidebar:
  order: 1
---

Agent Session Record (ASR) is an open file format for coding agent sessions. Each session is one UTF-8 JSON Lines file holding its prompts, replies, tool calls, file edits and commits. The current format version is `0.1`.

## Terms

- A **source** is the native log, export, hook or live connection a fact comes from.
- A **producer** is software that writes ASR. A **writer** is a producer that claims conformance.
- A **reader** is software that displays or indexes ASR, or derives answers from it.
- A **stream** is the ordered records for one session.
- A **harness** is the program that runs the agent, such as Claude Code or Codex.
- An **inference** is one model call.

## Questions ASR answers

The core records support these questions, most important first.

1. Which session wrote this line, from which prompt, with which model?
2. Which sessions made this commit or pull request, and what else did they do?
3. Which sessions read or changed this file?
4. Where does this text appear in prompts, replies or tool input and output across agents?
5. What happened in this session, in order?
6. What failed, and what happened next?
7. What did it cost, by model?
8. Which session started which subagent, with what task, and what came back?
9. Was the change kept, reverted or merged?

Answers cite recorded facts. A fact with no recorded evidence stays unknown. The prompt and any recorded explanation can help show why a change happened. [Code links and blame](code.md) separates the session that edited a line from the session or person that committed it. [Annotations](annotations.md) add outcomes learned later.

## A small session

The first line identifies the session and the software that wrote the file. Each later line is one completed item.

```jsonl
{"type":"session","id":"header","formatVersion":"0.1","agent":{"name":"com.example.agent","version":"1.0"},"sessionId":"session-7","producer":{"name":"example-export","version":"1.0","method":"native"}}
{"type":"message","id":"prompt-1","role":"user","author":"human","origin":"prompt","content":[{"type":"text","text":"Explain the empty-input check."}]}
{"type":"message","id":"reply-1","role":"assistant","author":"model","phase":"final","content":[{"type":"text","text":"The check returns an empty list before parsing."}]}
```

Few fields are required. Times, model names, usage and repository details appear when the source records them. A missing field does not stand for a default value.

## How sessions get in

Most ASR files come from a converter that reads an agent's native logs after the session. An agent can also export ASR itself, with a command or by writing an ASR file next to its native log. A recorder watches a live connection or hooks and writes the items it sees.

The [agent list and converter notes](../agents/index.md) describe each native format and how it maps to ASR. The [integration guide](../guides/integration.md) covers the export command convention, the discovery file and the `Agent-Session` commit trailer.

## Records

There are ten core record types.

| Record | What it holds |
|---|---|
| [`session`](records.md#session) | Session identity, producer and starting facts |
| [`session_info`](records.md#session_info) | Settings, offered tools, totals and newly discovered losses |
| [`message`](records.md#message) | Prompts, replies and recorded instructions |
| [`tool_call`](records.md#tool_call) | A tool request and the arguments it received |
| [`tool_result`](records.md#tool_result) | A tool's recorded outcome and output |
| [`approval`](records.md#approval) | One decision, with its own ID and position |
| [`file_change`](records.md#file_change) | One changed file and its edit evidence |
| [`vcs`](records.md#vcs) | Version-control actions and pull request references |
| [`inference`](records.md#inference) | One recorded model call |
| [`gap`](records.md#gap) | A position where history is missing |

## Related formats and scope

ASR reuses MCP content and ACP tool shapes. Guides cover [ACP recording](../guides/acp.md), [Git AI notes](../guides/git-ai.md) and [OpenTelemetry export](../guides/otel.md).

An ASR file is a log for indexing and search. It does not guarantee exact model context, replay, resume, completeness, chat delivery, truth or safe sharing.

For use across a company, see the [company guide](../guides/organizations.md) and the [audit guide](../guides/audits.md).

## Reading the specification

These eight pages are normative. Guides and agent notes are not.

| Page | What it defines |
|---|---|
| [Overview](overview.md) | Terms, scope and conventions |
| [Format](format.md) | Framing, order, identity, paths, content and extensions |
| [Records](records.md) | The ten core record types |
| [Sessions](sessions.md) | Parents, subagents and copied history |
| [Code links and blame](code.md) | Repository checks and attribution |
| [Missing data](missing-data.md) | Unknown values, gaps and safety |
| [Annotations](annotations.md) | Facts learned after a session |
| [Conformance](conformance.md) | Writer, reader and validator requirements |

The words MUST, MUST NOT, SHOULD, SHOULD NOT and MAY have the meanings in [BCP 14](https://www.rfc-editor.org/info/bcp14) when written in capitals. The numbered requirements are the obligations for implementations. Field tables define the shapes they use. In the Req column, R means required, O means optional and C means required under the stated condition. Listed enum values are open to extension. Examples that start with a `session` header are whole streams. Examples without one are record excerpts.
