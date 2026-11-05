---
title: "Using ASR for audits"
description: "Read approval evidence, record collection receipts and check sessions against independent systems."
---

ASR can help a company follow a change from a prompt through tool activity to a commit. It can show recorded approvals, policy settings and missing evidence in the same file. This guide describes how to collect and assess those files. It adds no requirements to the format.

## What a session can show

A converted session is a copy of what the machine kept. The person running the agent can usually change or delete its native logs before collection. Validation establishes the shape of the exported record. It does not establish that the native log was complete or unchanged.

An ASR file written by the agent itself records what its instrumentation saw at the time. That can preserve details a later converter cannot recover. The file still lives on the user's machine. Its producer may miss events, stop writing or record a tool's incomplete account of its work.

Hooks and plugins can affect the evidence. Some agents allow them to rewrite tool input or output, and some let them rewrite or suppress saved messages. Many agents update their session stores in place. An export can therefore differ from the same session collected an hour before. Read the [converter notes](../agents/index.md) for the source's capture and retention limits.

A company collector can preserve exact received bytes and their digests. With protected receipts, this shows whether a file changed after it was received. It cannot establish what happened before receipt or reveal a session that was never submitted. A digest alone also cannot expose an attacker who can replace both the file and its receipt.

The strongest supporting evidence comes from systems the person running the agent does not control. Compare sessions with the Git forge, CI, and vendor admin or usage exports. A forge review, CI result and collected session answer different questions. Keep their source and collection time visible when joining them.

## Read approvals as decisions

Each `approval` record holds a decision at its source position, or before its result under the [snapshot rule](../spec/format.md#file-format-and-order), with its own ID and optional time. A call can need several decisions, such as permission to run a command and permission to escape its sandbox. Join them by `callId` only when the call is unique. A grant with no call has a `subject` and no `callId`. `person` identifies the recorded answerer. `by` distinguishes a person from a rule, mode, hook, classifier or unattended fallback. A reused grant is a policy decision for the later call.

An approval does not establish that the tool ran or succeeded. A denial does not prove that no equivalent action happened elsewhere. Without a recorded decision, the answer stays unknown. A result's `approvalId` names the decision it followed. Without it, which decision applied stays unknown, even when only one decision is recorded. Compare the final decision for each subject with the result and other recorded effects. A denied subject with evidence it happened anyway is a finding. Read `scope` by lifetime: one request, the session, or a grant kept beyond the session. The agent's button label alone may not establish that lifetime.

Approvals inside a copied prefix or marked `copiedFrom` belong to the source session. Do not count them as decisions in the copying session.

Most converters need to list `approvals` in `missing`. Their sources may retain only denials, omit decisions, prune a separate store or send decisions to telemetry the converter did not read. A file can contain some decisions while still declaring this loss. Take the union of header losses and `session_info.missing` updates. Do not infer an approval from a completed result or a permissive mode.

Claude Code and Codex provide useful examples of separate OpenTelemetry evidence. Claude Code's `claude_code.tool_decision` includes `tool_use_id`, `decision` and `source`. Codex's `codex.tool_decision` includes `call_id`, `decision` and optional `source`. A converter can join those IDs to ASR `callId` within the identified session and write approval records at the decisions' positions. Keep repeated decisions in source order and avoid adding the same event twice.

The [Claude Code](../agents/claude-code.md) and [Codex](../agents/codex.md) notes describe the decision and scope mappings. A file that imports telemetry still lists `approvals` in `missing` when coverage is incomplete.

## Read policy at the right position

Use the `session_info.agentSettings` updates before each action or decision in file order. Native `approval` and `sandbox` values preserve the source policy. `asks` describes what that policy can require before file changes or commands. It does not count prompts. When `mode`, `approval` or `sandbox` changes without `asks`, the earlier summary becomes unknown.

`externalSandbox` records a boundary outside the agent process when the source states one. A sandbox used only by some tools does not establish that boundary. A latest-value snapshot does not establish an earlier boundary or prove it was configured correctly. Configured `modelSettings` merge field by field, with `null` clearing a fact, and stay distinct from settings recorded for an inference. Neither a later configuration file nor a documented default supplies historical values.

`session_info.tools` records the captured offered definitions from that position until a replacement list arrives. A `tools` loss means the list may be partial. System and developer messages with `origin: instructions` keep recorded instructions at their stream positions. These fields can contain private instructions and follow the same access and safety rules as other content.

`message.origin` distinguishes a scheduled message from one delivered by an outside event. `author` and `person` describe authorship separately. Keep native schedule and delivery IDs in `_meta` for a join to the system that delivered the work. A headless run alone does not identify its trigger.

## Write a collection manifest

The company's collection server can write one plain JSON manifest per machine per collection window, including windows with no entries. Use the [manifest schema](https://agentsessionrecord.org/schema/v0/manifest.schema.json) and [example receipt](https://agentsessionrecord.org/examples/collection.manifest.json). The example's digest and byte length identify the exact `approvals-and-policy.jsonl` file in the repository's examples.

| Field | Presence | Meaning |
|---|---|---|
| `$schema` | Required | `https://agentsessionrecord.org/schema/v0/manifest.schema.json` |
| `collector` | Required | Object with `name` and `version` strings |
| `machine` | Required | Stable machine ID string assigned by the collector |
| `window` | Required | Object with RFC 3339 `start` and `end` |
| `previousManifest` | Required | Object with `sha256` for this machine's preceding manifest, or `null` for its first window |
| `entries` | Required | Array of receipts, including an empty array for an empty window |

A window includes its start and excludes its end. Its start precedes its end. Place each receipt in the window containing its collector receipt time. Check window order and missing intervals when comparing manifests.

Each entry describes one receipt or reported collection failure.

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

For `received`, include the session, digest, byte length and producer. For `unreadable`, retain the full bytes' digest and length with a reason, and leave out any header fact you could not read. For `failed`, record the reason without inventing a file digest. Its receipt time is when the collector received the failure report. Status values remain open to extension. The validator warns about unfamiliar statuses, reversed or empty windows, and receipt times outside their window.

Hash exact bytes, including newlines. Do not hash parsed and reserialized JSON. Take receipt times from the collector's clock, never from session event times. A re-export adds an entry with `replaces` instead of editing an existing entry. The session reference stays the same while the file digest can change. A redacted copy can also carry `derivedFrom.sha256` pointing to its source file, with losses still recorded in the stream.

Keep windows in order and link each to the preceding manifest's exact bytes. Check for gaps and ensure no two manifests for one machine share a `previousManifest`. A retained link makes a deleted intervening window visible. Keep the latest manifest digest in independently protected storage to detect loss of the tail too. An empty manifest records a collection window, not proof that the machine ran no agents. An empty manifest written for a machine the collector could not reach says only that nothing arrived. Record unreachable machines as failed collection in the collector's own log, not as an empty window presented as checked. Signing and write-once storage are optional protections using existing tools. A manifest can be wrapped in an [in-toto statement](https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md) for signing.

## Operate the store and sample the evidence

Write-once retention and legal hold belong in the store. When a file arrives, compare its `user` with the signed-in uploader. Write down the company rule for what happens when they differ. Keep the mismatch for review. Do not overwrite the recorded user. Keep both identities and flag mismatches. Keep machine and collector clocks in sync. For claims about a collection period, use manifest receipt times and report late or failed uploads separately.

Collect only the metadata and content needed for the stated purpose. This reduces the personal data the store holds. Apply access and retention rules to identities, prompts, tool output, indexes and backups together. The [company guide](organizations.md) covers directory joins and shared access.

Each month, compare manifests with Git history and vendor usage. Investigate missing windows, failed uploads, unexplained usage and changes without session links. Expect the counts to differ. One vendor request is one model call, not one session.

For an auditor's sample, start with a commit, use blame to select a changed line, then follow its session, approval, forge review and CI result. Apply the [blame checks](../spec/code.md) and show every unresolved link. Keep the evidence that supports the answer alongside the limits that prevent a stronger one.
