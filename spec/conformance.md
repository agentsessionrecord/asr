---
title: Conformance
description: Writer and reader obligations, validation and the requirement table.
sidebar:
  order: 8
---

ASR defines conformance for writers, readers and validators. One implementation can perform several of these roles. A valid file establishes structure, not that its producer faithfully recorded the source.

## Writers

**ASR-067** A conforming writer MUST emit streams that pass validation and follow the missing-data rules. For each converter mapping, it MUST publish a sample native file and the source versions it supports.

Samples let reviewers compare native facts with exported records. They exclude known secrets under the [safety rules](missing-data.md#safety). Passing a schema cannot prove that a converter kept the right model, outcome or authorship. Those claims need comparison with source data.

## Readers

**ASR-068** A conforming reader MUST follow the rules for file order, unknown data, conservative call pairing, copied-record credit, blame and accounting. It MUST show gaps and unresolved references and MUST follow the safety rules for untrusted content.

An indexer can support search without offering blame. When it does derive attribution, the [code-link checks](code.md) apply. A storage tool also preserves unknown data so a later reader can use it.

## The validator

The record schemas live at `schema/v0/agent-session.schema.json` and `schema/v0/annotation.schema.json`. A validator checks framing and relationships across records as well as individual record shapes.

**ASR-069** A validator MUST report the following as errors when applicable to the file being checked.

- Invalid UTF-8 or JSONL framing, malformed complete records or duplicate object keys.
- A session stream whose first line is not its only `session`, or whose `formatVersion` is unsupported.
- A core record or known annotation payload that fails its JSON Schema.
- Duplicate or malformed record IDs.
- An inference without `model` when the session does not list `model` in `missing`.
- More than one `tool_result` for the same `callId`.
- Both `commit` and `commitPrefix`, or malformed commit IDs, prefixes or file object IDs.
- Disagreement between `parents` and `parentCount`, a rewrite pair with identical endpoints, or mixed full commit ID lengths within a `vcs` record or `vcs` annotation payload.
- A `parent.copiedThrough` that does not name a record after the header in the same file.
- Both `input` and `inputText`, both `patch` and `edits`, or a move or copy without `oldPath`.
- Both `callId` and `actor` on a `file_change` record, a `vcs` record or a `vcs` annotation payload.
- A malformed session reference or an annotation `supersedes` that does not name an earlier annotation in its file.

**ASR-070** A validator MUST warn about a call without a result, an unpaired result, an `approval` with a `callId` but no unique matching call, an `inferenceId` without a matching `inference`, a tool call without `name`, an incomplete final line, and unknown record types or extensions.

An incomplete final line is a warning, not an error. Unknown types, fields, enum values and content parts do not become errors merely because they are unfamiliar. An unavailable related session is not an error.

**ASR-071** A validator MUST NOT query Git, the network or native formats to validate a file, and MUST NOT claim that passing validation proves a writer was faithful.

Repository checks belong to a reader deriving blame. Source comparisons belong to tests of the writer's converter mapping. The validator's structural result does not replace either.

This excerpt illustrates a call whose outcome is unknown. In a stream with no result for it, the validator warns.

```jsonl
{"type":"tool_call","id":"read-call","callId":"read-1","name":"read_file","kind":"read","input":{"path":"/work/app/src/parser.py"}}
```

## Collection manifests

The collection manifest is a companion document described in the [audit guide](../guides/audits.md#write-a-collection-manifest). It has no numbered requirements. ASR conformance neither requires nor forbids checking it.

## Requirement table

The table lists every numbered requirement in page order. Requirement IDs are stable once assigned and are never reused. `schema` means a record-shape check, `semantic` means a file or cross-record check, and `fixture` means implementation behavior checked with examples or native source fixtures. A row names its main check. Some requirements also need behavioral evidence. Conformance fixtures belong in `conformance/fixtures/`, alongside the readable sessions in `examples/`.

| ID | Page | Summary | Check |
|---|---|---|---|
| ASR-078 | [Format](format.md) | Stable requirement IDs and meanings with versioned breaking changes | fixture |
| ASR-001 | [Format](format.md) | UTF-8 JSONL objects, LF framing and unique object keys | semantic |
| ASR-002 | [Format](format.md) | Exactly one session header on line 1 with version 0.1 | semantic |
| ASR-003 | [Format](format.md) | Completed items in source order, never reordered by time | fixture |
| ASR-075 | [Format](format.md) | Folded completion positions, receipt order and snapshot approvals | fixture |
| ASR-077 | [Format](format.md) | String encoding for large native values and exact numeric preservation | fixture |
| ASR-004 | [Format](format.md) | Live writers append and converters can re-export | fixture |
| ASR-005 | [Format](format.md) | Recover after malformed lines and defer incomplete tails | fixture |
| ASR-006 | [Format](format.md) | Common envelope fields and shapes | schema |
| ASR-007 | [Format](format.md) | Record ID shape and uniqueness | semantic |
| ASR-008 | [Format](format.md) | Native or deterministic opaque IDs and external citations | fixture |
| ASR-009 | [Format](format.md) | Source times and explicit live lifecycle receipt times | fixture |
| ASR-010 | [Format](format.md) | Agent names, native session IDs and installation namespaces | fixture |
| ASR-011 | [Format](format.md) | Reference grammar, encoding and session-only targets | schema |
| ASR-012 | [Format](format.md) | Absolute and relative paths, with embedded paths preserved | fixture |
| ASR-013 | [Format](format.md) | Ordered content parts and part-level overrides | schema |
| ASR-014 | [Format](format.md) | Exact text and concatenated streaming deltas | fixture |
| ASR-015 | [Format](format.md) | Reasoning visibility without encrypted content or provider state | fixture |
| ASR-016 | [Format](format.md) | Preserve unknown data and keep enums open | fixture |
| ASR-017 | [Format](format.md) | Vendor field, record type, content-part type and enum naming | schema |
| ASR-018 | [Format](format.md) | Extensions are declared and preserve core meanings | fixture |
| ASR-019 | [Records](records.md) | Session shape, non-empty sourced identities, authorship limits and repositories | schema |
| ASR-020 | [Records](records.md) | Session updates, verbatim policies, per-field settings, null clears and whole outer boundaries | fixture |
| ASR-072 | [Records](records.md) | Asking from recorded policy, invalidation on changes and stated outer boundaries | fixture |
| ASR-074 | [Records](records.md) | Recorded offered tools, partial-list losses and whole-list replacement | fixture |
| ASR-021 | [Records](records.md) | Message role, content and optional fields | schema |
| ASR-022 | [Records](records.md) | Human authorship and compaction summaries | fixture |
| ASR-023 | [Records](records.md) | Tool call fields and exclusive input forms | schema |
| ASR-024 | [Records](records.md) | Native call IDs, names, kinds and request authorship | fixture |
| ASR-025 | [Records](records.md) | Recorded tool outcomes, exit codes and model-facing output | fixture |
| ASR-076 | [Records](records.md) | Effective tool input learned at completion and exclusive forms | schema |
| ASR-026 | [Records](records.md) | One result per call ID and pairing only to a unique call | semantic |
| ASR-073 | [Records](records.md) | Approval records, source order, reused grants and real lifetimes | fixture |
| ASR-027 | [Records](records.md) | File changes, move origins and exclusive edit and actor forms | schema |
| ASR-028 | [Records](records.md) | Applied changes and observed actors | fixture |
| ASR-029 | [Records](records.md) | Historical file content and recorded patches | fixture |
| ASR-030 | [Records](records.md) | File object ID types, lengths and default | schema |
| ASR-031 | [Records](records.md) | VCS fields, exclusive actors, commit IDs and PR identity | schema |
| ASR-032 | [Records](records.md) | Parent counts, distinct rewrites and consistent commit lengths | semantic |
| ASR-033 | [Records](records.md) | Actions and references come from source evidence | fixture |
| ASR-034 | [Records](records.md) | Model calls come from source boundaries | fixture |
| ASR-035 | [Records](records.md) | Optional model with declared loss, distinct identities and sourced settings | schema |
| ASR-036 | [Records](records.md) | Inclusive usage totals and recorded zeros | fixture |
| ASR-037 | [Records](records.md) | Cost amount, currency and unknown values | schema |
| ASR-038 | [Records](records.md) | Per-call accounting excludes copies and session totals | fixture |
| ASR-039 | [Records](records.md) | Gap fields and corrupt-source reporting | fixture |
| ASR-040 | [Sessions](sessions.md) | Parent and copy-source shapes | schema |
| ASR-041 | [Sessions](sessions.md) | Copied prefix ends at a local record after the header | semantic |
| ASR-042 | [Sessions](sessions.md) | Lineage only from native evidence and known copy losses | fixture |
| ASR-043 | [Sessions](sessions.md) | Copies receive no credit and new child calls do | fixture |
| ASR-044 | [Sessions](sessions.md) | Combine subagent links and allow unavailable sessions | fixture |
| ASR-045 | [Sessions](sessions.md) | Stable resume identity and retained native branches | fixture |
| ASR-046 | [Code links and blame](code.md) | Git blame and repository path checks | fixture |
| ASR-047 | [Code links and blame](code.md) | Exact rewrites carry history with surviving edit checks | fixture |
| ASR-048 | [Code links and blame](code.md) | Commit status decides, with fallback only for unknown | fixture |
| ASR-049 | [Code links and blame](code.md) | Verify full commits or every short-ID check | fixture |
| ASR-050 | [Code links and blame](code.md) | Match only edit-added lines and exclude dirty context | fixture |
| ASR-051 | [Code links and blame](code.md) | Surviving edits, alternatives and actor attribution | fixture |
| ASR-052 | [Code links and blame](code.md) | Separate edit and commit credit with recorded model links | fixture |
| ASR-053 | [Code links and blame](code.md) | PR actions and membership for multi- and single-parent merges | fixture |
| ASR-054 | [Code links and blame](code.md) | Trailer and Git AI links require checks | fixture |
| ASR-055 | [Missing data](missing-data.md) | Absence is unknown and falsy values are real | fixture |
| ASR-056 | [Missing data](missing-data.md) | Do not invent native facts | fixture |
| ASR-057 | [Missing data](missing-data.md) | Declare known losses in the header or later updates and keep their union | fixture |
| ASR-058 | [Missing data](missing-data.md) | Mark shortened text and missing history | fixture |
| ASR-059 | [Missing data](missing-data.md) | Untrusted content without fetching or execution | fixture |
| ASR-060 | [Missing data](missing-data.md) | Exclude secrets, identify derived-file producers and link exact source bytes | fixture |
| ASR-061 | [Annotations](annotations.md) | Later facts use a separate annotations file | fixture |
| ASR-062 | [Annotations](annotations.md) | Annotation identity, target, source and learned time | schema |
| ASR-063 | [Annotations](annotations.md) | Kind-specific payloads and open values | schema |
| ASR-064 | [Annotations](annotations.md) | Corrections name earlier annotations | semantic |
| ASR-065 | [Annotations](annotations.md) | Corrections first, current values by time, additive tests and VCS | fixture |
| ASR-066 | [Annotations](annotations.md) | Annotations inform links without granting blame credit | fixture |
| ASR-067 | [Conformance](conformance.md) | Writers validate, declare losses and publish mapping samples | fixture |
| ASR-068 | [Conformance](conformance.md) | Readers follow interpretation and safety rules | fixture |
| ASR-069 | [Conformance](conformance.md) | Validator errors cover structural and relational checks | fixture |
| ASR-070 | [Conformance](conformance.md) | Validator warnings cover incomplete and unfamiliar data | fixture |
| ASR-071 | [Conformance](conformance.md) | Validation is offline and cannot prove faithfulness | fixture |
