---
title: Missing data
description: Unknown values, known losses, gaps and safe handling.
sidebar:
  order: 6
---

ASR records what the source makes available. Missing information is part of the record's meaning. A small stream can be useful without supplying every fact a reader might want.

## Unknown values

**ASR-055** Readers and producers MUST treat an omitted field as unknown, never as false, zero, success or empty. They MUST preserve recorded `false`, `0` and `""` as real values.

In a settings update, omission keeps the last supplied value and `null` clears it under [ASR-020](records.md#session_info).

An empty content array says the source recorded no parts in that message. An absent cost says nothing about whether the call was free. A call without a result does not imply failure or success.

**ASR-056** Producers MUST NOT invent IDs that appear native, times, models, outcomes, exit codes, costs or authorship.

Deterministically derived IDs are allowed by the [identity rules](format.md#envelope). A requested model stays requested until the source identifies the model that served the call. File contents read during export do not establish historical file contents. An estimated cost is recorded as an estimate under the [cost shape](records.md#usage-and-cost).

## Known losses

**ASR-057** A producer MUST list in `session.missing` every loss it knows it introduced or inherited, using an array of open strings. It MAY declare a newly discovered loss in the next `session_info.missing`. Readers MUST take the union of the header and all later loss updates. An update MUST NOT remove a loss. An empty header array MUST mean no losses are known, not that capture is complete.

The recommended names are `reasoning`, `usage`, `timestamps`, `tool_output`, `exit_codes`, `file_changes`, `commits`, `subagents`, `copies`, `model`, `approvals`, `agent_settings` and `tools`. Other strings can describe other known losses. These are names of missing information, not switches that invalidate the rest of the stream.

`tools` means the offered tool list is missing or known to be partial.

`approvals` means the stream may not hold every approval decision, for example because the source saves only denials, prunes decisions or keeps them in telemetry the converter did not read.

`agent_settings` means known missing or incomplete evidence about agent mode, approval policy, sandbox policy or configured model settings. The source or producer may have omitted it, and recorded history may be incomplete. This name does not require every optional setting to be captured.

An empty `session_info.missing` adds no losses and removes none. A gap still marks the affected position when history was lost.

For example, a converter can preserve tool requests while lacking file-change normalization. It lists `file_changes` in `missing` while the requests remain searchable. A loss inherited from an incomplete native log is still a known loss.

## Shortened text and missing history

**ASR-058** A producer MUST set `truncated: true` on any record whose text was shortened by the source or producer, and MUST place a `gap` where history is known to be missing. Readers MUST NOT treat a gap, or the absence of one, as proof that an event did not happen.

Removing a record's text while keeping the record uses `truncated`, and removing records uses a `gap`.

`missing` describes known limits of the session record. `truncated` marks shortened text on a particular record. A gap marks missing history at a place in the stream. Its optional count is used only when the number of missing records or source lines is known.

This example keeps the available summary and marks the history lost during compaction.

```jsonl
{"type":"session","id":"header","formatVersion":"0.1","agent":{"name":"com.example.agent"},"sessionId":"session-8","producer":{"name":"example-converter","version":"1.0","method":"converter","source":"example-jsonl"},"missing":["tool_output","usage","timestamps"]}
{"type":"message","id":"summary-1","role":"user","author":"harness","origin":"compaction","truncated":true,"content":[{"type":"text","text":"Work so far: inspected the parser."}]}
{"type":"gap","id":"gap-1","reason":"not_retained","detail":"The native log retains this summary but not the earlier messages and tool output."}
```

The summary is searchable. Its description of work does not become a file edit or a commit record.

## Safety

**ASR-059** Readers MUST treat all stream content as untrusted, MUST NOT fetch URIs or run commands found in a stream, and MUST NOT present successful validation as meaning the stream is safe to share.

Render recorded text as data. Resource links, embedded content, patches and tool arguments can contain instructions that were never addressed to the reader. Repository checks for blame are operations chosen by the reader, not execution of commands taken from the stream.

**ASR-060** Producers MUST exclude known secrets, including credentials and secret answers to prompts, from records and `_meta`. Redaction MUST produce a new file rather than a tombstone or an in-place rewrite of the original stream. In a derived file, `producer` MUST name the software that made it, with `method: "converter"` and `source` naming the input it read. When supplied, `derivedFrom.sha256` MUST be 64 lowercase hexadecimal digits hashing the exact bytes of the ASR file this file was made from. Producers MUST still record losses in `missing`, `truncated` and `gap` as applicable.

Safety takes precedence over text preservation. Record known losses, shortened text and missing history in the redacted file as applicable. Excluding known secrets does not guarantee that the remaining content is suitable for publication.
