---
title: Missing data
description: Unknown values, known losses, gaps and safe handling.
sidebar:
  order: 6
---

A producer records only what its source makes available. A stream can be useful without every fact a reader might want. Agent Session Record marks what is unknown so that readers do not fill it in.

## Unknown values

**ASR-055** Readers and producers MUST treat an omitted field as unknown, never as false, zero, success or empty. They MUST preserve recorded `false`, `0` and `""` as real values.

In a settings update, omission keeps the last supplied value and `null` clears it under [ASR-020](records.md#session_info).

An empty content array means the source recorded no parts in that message. A missing cost says nothing about whether the call was free. A call without a result does not imply failure or success.

**ASR-056** Producers MUST NOT invent IDs that appear native, times, models, outcomes, exit codes, costs or authorship.

The [identity rules](format.md#envelope) allow deterministic derived IDs. A requested model stays requested until the source names the model that served the call. Reading a file during export does not show what it held during the session. An estimated cost is marked as an estimate under the [cost shape](records.md#usage-and-cost).

## Known losses

**ASR-057** A producer MUST list in `session.missing` every loss it knows it introduced or inherited, using an array of open strings. It MAY declare a newly discovered loss in the next `session_info.missing`. Readers MUST take the union of the header and all later loss updates. An update MUST NOT remove a loss. An empty header array MUST mean no losses are known, not that capture is complete.

The recommended names are `reasoning`, `usage`, `timestamps`, `tool_output`, `exit_codes`, `file_changes`, `commits`, `subagents`, `copies`, `model`, `approvals`, `agent_settings` and `tools`. Other strings can name other known losses. A listed loss does not invalidate the rest of the stream.

`tools` means the offered tool list is missing or known to be partial.

`approvals` means the stream may not hold every approval decision, for example because the source saves only denials, prunes decisions or keeps them in telemetry the converter did not read.

`agent_settings` means evidence about agent mode, approval policy, sandbox policy or configured model settings is known to be missing or incomplete. The name does not require a producer to capture every optional setting.

An empty `session_info.missing` adds no losses and removes none. When history was lost, a gap still marks where.

For example, a converter that keeps tool requests but cannot turn them into file changes lists `file_changes` in `missing`. The requests stay searchable.

## Shortened text and missing history

**ASR-058** A producer MUST set `truncated: true` on any record whose text was shortened by the source or producer, and MUST place a `gap` where history is known to be missing. Readers MUST NOT treat a gap, or the absence of one, as proof that an event did not happen.

Use `truncated` when a record stays but loses some of its text. Use a `gap` where whole records are missing. A gap's optional count is set only when the number of missing records or source lines is known. `missing` lists the known losses for the whole session.

Here a compaction summary survives, but the history before it does not.

```jsonl
{"type":"session","id":"header","formatVersion":"0.1","agent":{"name":"com.example.agent"},"sessionId":"session-8","producer":{"name":"example-converter","version":"1.0","method":"converter","source":"example-jsonl"},"missing":["tool_output","usage","timestamps"]}
{"type":"message","id":"summary-1","role":"user","author":"harness","origin":"compaction","truncated":true,"content":[{"type":"text","text":"Work so far: inspected the parser."}]}
{"type":"gap","id":"gap-1","reason":"not_retained","detail":"The native log retains this summary but not the earlier messages and tool output."}
```

The summary is searchable, but the work it describes does not become file edits or commit records.

## Safety

**ASR-059** Readers MUST treat all stream content as untrusted, MUST NOT fetch URIs or run commands found in a stream, and MUST NOT present successful validation as meaning the stream is safe to share.

Show recorded text as data. Resource links, embedded content, patches and tool arguments can hold instructions that were never meant for the reader. The repository checks for blame are operations the reader chooses. They do not run commands taken from the stream.

**ASR-060** Producers MUST exclude known secrets, including credentials and secret answers to prompts, from records and `_meta`. Redaction MUST produce a new file rather than a tombstone or an in-place rewrite of the original stream. In a derived file, `producer` MUST name the software that made it, with `method: "converter"` and `source` naming the input it read. When supplied, `derivedFrom.sha256` MUST be 64 lowercase hexadecimal digits hashing the exact bytes of the ASR file this file was made from. Producers MUST still record losses in `missing`, `truncated` and `gap` as applicable.

Removing secrets takes priority over keeping text intact. A file with its known secrets removed is not necessarily safe to publish.
