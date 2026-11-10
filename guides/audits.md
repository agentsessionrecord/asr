---
title: "Using ASR for audits"
description: "Read approval evidence, record collection receipts and check sessions against independent systems."
---

An Agent Session Record (ASR) file can help a company follow a change from a prompt through tool activity to a commit, with the recorded approvals, policy settings and missing evidence in the same file.

## What a session can show

A converted session is a copy of what the machine kept, and the person running the agent can usually change or delete those logs before collection. Some agents let hooks and plugins rewrite tool input or output, or rewrite or suppress saved messages, and many update session stores in place, so an export can differ from the same session collected an hour earlier. A file the agent writes itself can keep more detail, but it also lives on the user's machine, and its producer may miss events, stop writing or record a tool's incomplete account of its work. Validation checks only the export's shape. The [converter notes](../agents/index.md) give each source's capture and retention limits.

With protected receipts, a collector that keeps the exact received bytes and their digests can show whether a file changed after it arrived. It can't show what happened before receipt or reveal a session that was never submitted, and a digest alone can't expose an attacker who can replace both the file and its receipt. Stronger evidence comes from systems the person running the agent doesn't control, such as the Git forge, CI and vendor admin or usage exports. Keep each source and its collection time visible when you join them.

## Approvals

Each [`approval` record](../spec/records.md#approval) is one decision, and one call can have several. With no recorded decision, the answer is unknown. An approval doesn't establish that the tool ran or succeeded, and a denial doesn't prove that no equivalent action happened elsewhere. Which decision a result followed is known only from its `approvalId`, even when just one decision is recorded. Compare the final decision for each subject with the result and other recorded effects, since a denied subject that happened anyway is a finding. Copied approvals belong to the session they were copied from.

Most converters have to list `approvals` as missing, because their sources may keep only denials, omit decisions, prune a separate store or send decisions to telemetry the converter didn't read. A file can hold some decisions and still declare this loss, so check the header's losses and every later `session_info.missing` update.

Claude Code and Codex also report decisions through OpenTelemetry, as `claude_code.tool_decision` with `tool_use_id`, `decision` and `source`, and `codex.tool_decision` with `call_id`, `decision` and optional `source`. A converter can join those IDs to `callId` within the identified session and write approval records at the decisions' positions, in source order and without duplicates. The [Claude Code](../agents/claude-code.md) and [Codex](../agents/codex.md) notes give the mappings.

## Policy and settings

The settings in effect for an action are the [`session_info.agentSettings`](../spec/records.md#session_info) updates before it in the file. The native `approval` and `sandbox` values are the source's own policy. `asks` only summarizes what that policy can require before file changes or commands, and it becomes unknown when `mode`, `approval` or `sandbox` changes without a new `asks`. `externalSandbox` appears only when the source states a boundary outside the agent process, and a latest-value snapshot of it doesn't establish an earlier boundary or prove it was configured correctly. Later configuration files and documented defaults don't show what was in effect earlier.

The offered tools and the system and developer instructions are recorded at their positions too. `message.origin` marks scheduled work and work delivered by an outside event, and native schedule and delivery IDs in `_meta` allow a join to the system that delivered it. A headless run alone doesn't identify its trigger.

## Write a collection manifest

The company's collection server can write one plain JSON manifest per machine per collection window, including windows with no entries. See the [manifest schema](https://agentsessionrecord.org/schema/v0/manifest.schema.json) and the [example receipt](https://agentsessionrecord.org/examples/collection.manifest.json), whose digest and byte length identify the exact `approvals-and-policy.jsonl` file in the repository's examples.

| Field | Presence | Meaning |
|---|---|---|
| `$schema` | Required | `https://agentsessionrecord.org/schema/v0/manifest.schema.json` |
| `collector` | Required | Object with `name` and `version` strings |
| `machine` | Required | Stable machine ID string assigned by the collector |
| `window` | Required | Object with RFC 3339 `start` and `end` |
| `previousManifest` | Required | Object with `sha256` for this machine's preceding manifest, or `null` for its first window |
| `entries` | Required | Array of receipts, including an empty array for an empty window |

A window includes its start and excludes its end, and its start comes before its end. Each receipt goes in the window that contains its collector receipt time. Each entry describes one receipt or reported collection failure:

| Field | Presence | Meaning |
|---|---|---|
| `session` | When readable | ASR session reference without a record fragment |
| `sha256` | When full bytes arrived | 64 lowercase hexadecimal digits hashing the exact received file |
| `byteLength` | When full bytes arrived | Non-negative integer length of those bytes |
| `receivedAt` | Required | RFC 3339 receipt time from the collector's clock |
| `uploader` | Required | Stable account ID string of the authenticated uploader |
| `producer` | When readable | Object with the file's recorded `method` string |
| `replaces` | When replacing a file | Object with `sha256` of the version replaced |
| `status` | Required | `received`, `failed`, `unreadable` |
| `reason` | For every status except `received` | Explanation of the collection result |

For `received`, include the session, digest, byte length and producer. For `unreadable`, keep the full bytes' digest and length with a reason, and leave out any header fact you couldn't read. For `failed`, record the reason without inventing a file digest, and use the time the collector received the failure report as the receipt time. Status values are open to extension. The validator warns about unfamiliar statuses, reversed or empty windows, and receipt times outside their window.

Hash the exact bytes, including newlines, not parsed and reserialized JSON. Take receipt times from the collector's clock, never from session event times. A re-export adds an entry with `replaces` rather than editing an existing one. A redacted copy can also carry `derivedFrom.sha256` pointing to its source file.

Link each manifest to the exact bytes of the one before it. Check for gaps, and check that no two manifests for one machine share a `previousManifest`. The links make a deleted window in the middle visible, and keeping the latest manifest's digest in independently protected storage shows a lost tail.

An empty manifest records a collection window, not proof that the machine ran no agents. When the collector can't reach a machine, record a failed collection in the collector's own log instead of presenting an empty window as checked. Signing and write-once storage are optional protections that use existing tools. For signing, a manifest can be wrapped in an [in-toto statement](https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md).

## Operate the store and sample the evidence

Write-once retention and legal hold belong in the store. When a file arrives, compare its `user` with the signed-in uploader, flag any mismatch for review under a written company rule, and keep both identities rather than overwriting the recorded one. Keep machine and collector clocks in sync, and base claims about a collection period on manifest receipt times, reporting late or failed uploads separately. Collect only the metadata and content the stated purpose needs, and apply access and retention rules to identities, prompts, tool output, indexes and backups together, as in [Running ASR across a company](organizations.md).

Each month, compare manifests with Git history and vendor usage, and investigate missing windows, failed uploads, unexplained usage and changes without session links. The counts won't match exactly, since one vendor request is one model call, not one session.

To sample for an auditor, start with a commit, use blame to pick a changed line, then follow its session, approval, forge review and CI result. Apply the [blame checks](../spec/code.md), show every unresolved link, and keep the limits that prevent a stronger answer next to the evidence.
