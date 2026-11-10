---
title: Format
description: JSON Lines, identity, paths, content parts and extensions.
sidebar:
  order: 2
---

An Agent Session Record (ASR) stream is one `.jsonl` file for one session. Its media type is `application/vnd.agent-session+jsonl`. Commands and other integrations name the format `agent-session`.

## Versions

**ASR-078** Requirement IDs MUST NOT be reused, record and field meanings MUST NOT change within a format version, and a breaking change MUST use a new `formatVersion`.

Version 0.1 is current. Changes to 0.1 only add optional fields, record types and enum values. Readers ignore additions they do not know and storage tools keep them, as [ASR-016](#unknown-data-and-extensions) requires. After a breaking change, the tools in this repository keep reading 0.1 files. A validator reports an unsupported format version as an error. From 1.0, a reader for 1.x reads every 1.x file, and changes within 1.x only add optional fields, record types and values.

## File format and order

**ASR-001** A writer MUST encode a stream as UTF-8 JSON Lines, with one JSON object per line, no blank lines, no duplicate object keys and an LF after each complete record.

**ASR-002** Line 1 MUST be the stream's only `session` record and MUST declare `formatVersion: "0.1"`.

**ASR-003** Writers MUST emit completed items in the order the source recorded them, and readers MUST keep file order rather than reorder records by `ts`.

Streaming chunks are assembled into one item before it is written. An interrupted reply can still be a completed item, with `status: "interrupted"`. There is no sequence field, and timestamps can be absent, equal or out of order. An `inferenceId` can point forward to a model call recorded after its output.

**ASR-075** A record folded from several native observations MUST occupy its completion point, with `ts` from the observation that completed it when that time is available. Intervening records MUST keep their positions. A live writer MUST use receipt order when the source exposes no total order. An approval without its own source position MUST go immediately before the result it concerns.

A folded record can keep its first observation time in `_meta`.

Below, a recorder receives a call at 12:00:00, a tool outcome at 12:00:01, a notice at 12:00:02 and the final model-facing output at 12:00:03, which completes the result. The approval decision is a snapshot stored on that result, with no source position of its own.

```jsonl
{"type":"session","id":"header","formatVersion":"0.1","agent":{"name":"com.example.agent"},"sessionId":"folded-7","producer":{"name":"example-recorder","version":"1.0","method":"recorder","source":"example-hooks"}}
{"type":"tool_call","id":"call","ts":"2026-10-31T12:00:00Z","callId":"run-7","name":"shell","inputText":"echo ready"}
{"type":"message","id":"notice","ts":"2026-10-31T12:00:02Z","role":"user","author":"harness","origin":"notice","content":[{"type":"text","text":"Another callback arrived."}]}
{"type":"approval","id":"decision","callId":"run-7","decision":"approved","native":{"decision":"allow"}}
{"type":"tool_result","id":"result","ts":"2026-10-31T12:00:03Z","callId":"run-7","status":"completed","content":[{"type":"text","text":"ready\n"}],"_meta":{"com.example.recorder":{"firstObservedAt":"2026-10-31T12:00:01Z"}}}
```

The notice stays between the call and the result, and the result keeps the final receipt time. The decision goes just before the result. It has no `ts` because the source gives no decision time, and its placement does not establish its order relative to other events. With no result to place it before, keep the snapshot in `_meta` and declare the missing approval history.

**ASR-077** Producers MUST write native IDs and other native values that may exceed 2^53 as strings, and readers MUST preserve numbers exactly as written.

ASR-077 covers values the specification does not type as numbers, such as native IDs, tool input, and content under `native` and `_meta`. Core numeric fields, such as token counts, limits, durations, amounts, exit codes, line numbers and byte lengths, stay JSON numbers. If a core count is outside the safe integer range, the producer omits that field, keeps the exact value as a string under its reverse-DNS key in `_meta`, and lists the loss in `missing` if a reader would otherwise miss it.

**ASR-004** A live writer MUST append records without rewriting a complete line. A converter MAY re-export the whole file.

**ASR-005** A reader MUST report and skip a malformed complete line, then continue, and MUST treat a non-empty final line without LF as incomplete rather than as an error or a complete record.

A reader waits for an incomplete final line to be finished before using it. A malformed line still fails validation, but skipping it lets an indexer keep the records around it. Corrupt data in a native log becomes a [gap](records.md#gap) when converted.

## Envelope

Every record, core or vendor, has these fields. [Records](records.md) defines the fields for each type.

| Field | Req | Meaning |
|---|---|---|
| `type` | R | String naming a core or vendor record type |
| `id` | R | Record ID unique in this file |
| `ts` | O | RFC 3339 event time |
| `turnId` | O | The source's turn ID |
| `inferenceId` | O | The `id` of the `inference` that produced this record |
| `copiedFrom` | O | Copy source with `session`, `record` or both, as defined in [Sessions](sessions.md#copies-and-credit) |
| `truncated` | O | Boolean, `true` when text in this record was shortened |
| `_meta` | O | Object containing vendor data under reverse-DNS keys |

**ASR-006** Every record MUST have `type` and `id` and MUST use the envelope field shapes above when those fields are present.

**ASR-007** Each record `id` MUST be a non-empty string of at most 256 characters with no control characters, and MUST be unique in the file.

**ASR-008** A producer MUST use a source record ID when it is unique in the file, otherwise derive an ID deterministically from native IDs or positions. Readers MUST treat IDs as opaque, and external record citations MUST use a session reference with a record fragment.

A derived ID does not claim that the agent assigned it.

**ASR-009** A producer MUST take event times from the source and MUST NOT invent absent times. A live recorder MUST use receipt time for `ts` and MAY set `startedAt` and `session_info.endedAt` from receipt of an explicit session start or end event from the agent. A turn stop, idle period or end of file MUST NOT set `endedAt`.

Export time never sets session times. A recorder can still list `timestamps` in `missing` when native times are unavailable.

A start event that arrives after the header is written does not set `startedAt`, and its receipt time can go in `_meta`. A recorder can hold back its first records, header included, until the start event arrives.

## Identity and session references

**ASR-010** `agent.name` MUST be a short name from the [agent list](../agents/index.md) matching `^[a-z0-9]+(-[a-z0-9]+)*$`, or a reverse-DNS name with at least one dot under a domain its maintainer controls. `sessionId` MUST be a non-empty native session ID verbatim, and `namespace` MUST be non-empty when used and used only when IDs repeat across installations.

The agent list is a JSON file, changed by pull request. The producer has its own `producer.name` and version, separate from the agent whose session it exports.

Each reverse-DNS label contains letters, digits or hyphens, and starts and ends with a letter or digit, as in `com.1example`. The same applies to vendor record types, vendor content-part types and `_meta` keys.

A session reference has one of these forms, with an optional record fragment.

```text
<agent>:<sessionId>
<agent>:<namespace>:<sessionId>
<agent>:<sessionId>#<recordId>
<agent>:<namespace>:<sessionId>#<recordId>
```

**ASR-011** Producers MUST use this session-reference grammar and percent-encode `%`, `:`, `#`, space and control characters inside each non-empty `namespace`, `sessionId` and `recordId` component, using uppercase hexadecimal digits for the encoded UTF-8 bytes. Fields naming a session MUST NOT include a record fragment.

The fields that name a session are `parent.session`, `copiedFrom.session`, `message.from` and `subagent.session` on calls and results. An annotation's `session` can name a session or a record.

Encoding applies only to references. The header keeps native values as they are. Readers split a reference into components before percent-decoding them, so `%23` inside a component is not a fragment. The prompt below is cited as `com.example.agent:run%3A7#prompt%201`.

```jsonl
{"type":"session","id":"header","formatVersion":"0.1","agent":{"name":"com.example.agent"},"sessionId":"run:7","producer":{"name":"example-converter","version":"1.0","method":"converter","source":"example-jsonl"},"cwd":"/work/app"}
{"type":"message","id":"prompt 1","role":"user","author":"human","content":[{"type":"text","text":"Read src/parser.py."}]}
```

## Paths

**ASR-012** Producers SHOULD write absolute paths when the source supplies one or they can resolve one. Other paths MUST use `/` separators and be relative to the session's `cwd`. Producers MUST NOT rewrite paths inside tool input, commands, output or patches.

Paths are plain strings. `cwd` is the absolute working directory at the start of the session. A relative path without a known `cwd` stays unresolved.

Readers match paths against `repos[].path` to find a candidate repository, then verify that repository when deriving blame. A recorded repository path can be a directory inside the repository's work tree. A repository path or remote alone does not establish that a commit exists there.

When a session lists no repository, a reader can treat `cwd` as a candidate location after checking that it lies inside the selected repository's real work tree. The reader resolves and normalizes each candidate file path against the selected Git root and rejects paths outside that work tree. On its own, this fallback does not supply a repository for a `vcs` action or establish edit or commit credit.

## Content parts

`message.content` and `tool_result.content` are ordered arrays of parts. Each part has a string `type`. A part can also carry `author` and `origin`, with the values defined for [messages](records.md#message), to override the message's values for that part.

| Type | Fields and meaning |
|---|---|
| `text` | Required `text` string |
| `image`, `audio` | MCP shapes with required string `mimeType` and optional base64 string `data`. Missing bytes mean the media was not captured |
| `resource_link` | MCP resource link shape, preserved verbatim |
| `resource` | MCP embedded resource shape, preserved verbatim |
| `reasoning` | Optional `text` string, `summary` array of strings and `visibility` |

A vendor content part names its owner in its type, as a vendor record does, and the owner defines its other fields. A producer that wraps a native block it cannot map keeps the block under its reverse-DNS key in `_meta`.

```jsonl
{"type":"message","id":"attachment","role":"user","content":[{"type":"com.example.agent/content","_meta":{"com.example.agent":{"native":{"type":"document","name":"notes.pdf"}}}},{"type":"text","text":"Read these notes."}]}
```

[MCP content blocks](https://modelcontextprotocol.io/specification/2026-07-28/server/tools) define the resource shapes. A resource link describes a resource, and an embedded resource carries its recorded contents. Neither gives a reader permission to fetch a URI.

**ASR-013** Producers MUST preserve content-part order and use the shapes above, including the string `type` on every part and part-level `author` and `origin` overrides when recorded.

**ASR-014** Text MUST be preserved byte-exact, subject to the [missing-data and safety rules](missing-data.md), and streaming text deltas MUST be joined only by concatenation.

Joining deltas does not insert spaces, normalize newlines or trim text. When one native item holds both injected instructions and a human prompt, part-level `author` and `origin` keep them apart.

**ASR-015** Reasoning `visibility` MUST describe the recorded representation. `encrypted` reasoning MUST carry no content, and producers MUST NOT record opaque provider state or signatures.

The known visibility values are `full`, `summary`, `encrypted` and `omitted`. A summary is not full reasoning. An `encrypted` reasoning part records only that encrypted reasoning was present.

## Unknown data and extensions

**ASR-016** Storage tools MUST preserve unknown record types, fields, enum values and content parts. Readers MUST ignore data they do not understand. All enums MUST remain open.

A reader that ignores an unknown content part still keeps the known parts beside it. An unfamiliar value is not necessarily a vendor value. It can be a core value the reader does not know.

**ASR-017** Vendor fields MUST go in `_meta` under reverse-DNS keys, vendor record types and vendor content-part types MUST use `<reverse-dns>/<name>`, and vendor enum values MUST start with `_`.

**ASR-018** A producer using a named extension MUST list it in `session.extensions`. Extensions MAY add records and fields but MUST NOT change the meaning of core records or require an unaware reader to interpret them.

Extension names are strings. No extension is required, and there are no conformance profiles. A reader can use the core records and ignore every extension in the file.
