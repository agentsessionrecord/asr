---
title: Annotations
description: Summaries, outcomes and other facts learned after a session.
sidebar:
  order: 7
---

An annotation is a fact learned after a session ends, such as a CI test result, a merge reported by a forge, or a title added by a person. Annotations never count as actions the session took.

## File and fields

**ASR-061** Facts learned after a session ends MUST be written in a separate file whose name ends in `.annotations.jsonl`, never added to the session's stream as session events. The file MUST use UTF-8 JSON Lines framing with one annotation per line and no session header.

Annotation lines follow the same [framing and recovery rules](format.md#file-format-and-order) as session streams. Each line uses this shape instead of the session record envelope.

| Field | Req | Meaning |
|---|---|---|
| `type` | R | `"annotation"` |
| `id` | R | ID unique in this annotations file |
| `session` | R | Session reference, optionally ending in `#<recordId>` |
| `kind` | R | `summary`, `outcome`, `test`, `vcs`, `title` |
| `at` | R | RFC 3339 time when the fact was learned |
| `source` | R | Object with required `name` and optional `version` identifying who learned it |
| `data` | R | Payload for the kind |
| `supersedes` | O | ID of an earlier annotation this one corrects |

**ASR-062** An annotation MUST have all required fields above, use a unique, well-formed record ID, and identify its target with a valid session reference. The `at` value MUST say when the fact was learned, not when an event in the session occurred.

One annotations file can cover several sessions. A target can point at a single record when the fact is about that record. If the target's file is missing, the reference stays unresolved and the annotation is still valid.

## Kinds

| Kind | Payload |
|---|---|
| `summary` | Required `text` string and optional `model` used for the summary |
| `outcome` | Required `status`, optional `commit`, `revertedBy` and `pr` |
| `test` | Required `status`, optional `commit`, `name` and `url` |
| `vcs` | The [type-specific `vcs` fields](records.md#vcs), including `action`, `status` and `evidence` |
| `title` | Required `title` string |

The known outcome statuses are `kept`, `reverted`, `merged` and `abandoned`. The known test statuses are `passed` and `failed`. Commit fields use full commit IDs. A pull request uses the `pr` shape from `vcs`.

**ASR-063** An annotation with a known kind MUST use that kind's payload above. Readers MUST keep kinds and status values open, ignore unfamiliar values and preserve them when storing annotations.

A test the agent ran during the session belongs in its stream as tool work. A CI result learned later is a `test` annotation. A generated summary is an annotation, not an assistant message.

```jsonl
{"type":"annotation","id":"title-1","session":"com.example.agent:session-7","kind":"title","at":"2026-10-27T09:00:00Z","source":{"name":"indexer","version":"1.0"},"data":{"title":"Parser fix"}}
{"type":"annotation","id":"outcome-1","session":"com.example.agent:session-7","kind":"outcome","at":"2026-10-27T10:00:00Z","source":{"name":"forge-sync","version":"1.0"},"data":{"status":"merged","pr":{"url":"https://example.com/team/app/pull/12","state":"merged","mergeCommit":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}}}
{"type":"annotation","id":"title-2","session":"com.example.agent:session-7","kind":"title","at":"2026-10-27T10:05:00Z","source":{"name":"reviewer"},"data":{"title":"Handle empty parser input"},"supersedes":"title-1"}
```

## Joining and corrections

**ASR-064** `supersedes` MUST name an earlier annotation ID in the same annotations file that the new annotation corrects.

The earlier line stays in the file. A correction does not rewrite the session or claim that the corrected fact was known earlier.

**ASR-065** Readers MUST join annotations by their target session reference and apply `supersedes` first, excluding corrected annotations from the current view. They MUST prefer the latest remaining `at` for each of `summary`, `outcome` and `title` on that target. They MUST retain all remaining `vcs` and `test` annotations as additive facts.

In the example, `title-2` replaces `title-1` through `supersedes`. A correction applies even if its `at` is older than that of the annotation it corrects. A target that names a record is separate from a target for the whole session. If two current values are equally recent and conflict, the reader can show the conflict rather than invent an order from the session stream.

**ASR-066** Readers MUST NOT give blame credit from an annotation alone. A `vcs` annotation MAY supply rewrite pairs, and a `vcs` or `outcome` annotation MAY supply `pr.mergeCommit` for the [code-link checks](code.md). These facts MUST NOT establish that the target session edited a line or performed a commit without its original session evidence.
