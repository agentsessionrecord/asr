---
title: "Running ASR across a company"
description: "Collect sessions, identify their users and manage shared storage and reporting."
---

A company can collect ASR files from many engineers into shared storage. Search and reporting tools read the same records regardless of which agent produced them. This guide describes one way to operate that store. It adds no required service, storage format or company vocabulary to ASR.

[Using ASR for audits](audits.md) covers evidence limits, approvals, collection manifests and checks against the forge, CI and vendor usage.

## Collect on each machine

Run a converter or exporter on each engineer's machine on a schedule. An agent's own export command can serve the same role. Select sessions changed since the last successful collection, validate the exports and upload one file per session. The [integration guide](integration.md) describes an export command convention and source discovery.

A live writer appends complete records. A converter can replace its entire export as the native session changes. Upload a replacement as a complete file, then update the index for that session. Retrying an upload should replace the same stored session rather than create another copy of its usage. Keep failed uploads available for retry and report source files that cannot be read.

An audit store can retain each received version and append a manifest entry while its searchable index shows the latest export. This preserves receipt history without counting replacement files as separate sessions.

## Identify the person

Set the header's `user` from an agent account or the repository's or user's Git identity. A company exporter can supply a directory ID with `source: "configured"`. Use a stable ID when available. Email addresses and display names can change or be shared. Record the real source of the identity and omit facts that source does not supply.

This illustrative header uses an identity configured by the company's exporter:

```jsonl
{"type":"session","id":"header","formatVersion":"0.1","agent":{"name":"com.example.coder"},"sessionId":"session-42","producer":{"name":"company-export","version":"1.0","method":"converter","source":"example-jsonl"},"user":{"id":"engineer-42","email":"alex@example.com","name":"Alex Rivera","source":"configured"},"_meta":{"com.example.company":{"team":"developer-tools","costCenter":"engineering"}}}
```

`user` identifies who ran the session as the source or machine knew them. It is useful for grouping and access labels. It does not prove who wrote a prompt or made a commit. Message `author` and the [blame rules](../spec/code.md) answer different questions. Authenticate the uploading exporter and check its identity assignment before using the label for access decisions.

## Keep company labels separate

An exporter can add team, department or cost-center labels under the company's own reverse-DNS key in `_meta`, as the example does. This serves a similar purpose to OpenTelemetry resource attributes. The company defines these labels and their meaning. They are not ASR core fields.

Prefer joining `user.id` to the company directory at query time. An engineer can move teams without rewriting every session file. A report can use current team membership or a directory history for membership at the time of the work. State which basis it uses. Labels stored in `_meta` are snapshots and can differ from the directory. Keep that distinction visible in reports.

## Choose storage keys

One possible object key is `<user>/<agent>/<encoded-session-reference>.jsonl`. Encode each component safely, without interpreting native IDs as paths. A stable directory ID avoids exposing an email address in object names. The path is an organizational choice. Session and user identity come from the records, not the path.

Deduplicate by the complete session reference, which includes the agent name. Add `namespace` only when native session IDs repeat across installations, and keep it stable for that installation. Uploading the same session through two collectors does not make two sessions. Keep annotations beside the exports or in a separate collection joined by their target references.

## Limit access

Sessions contain prompts, code and command output. Treat that content and the identity fields as sensitive. Limit access by person and repository, including when a session touches several repositories. Apply the same restrictions to search results, previews, downloads and derived indexes.

Exclude known secrets before upload. Successful validation checks structure and local relationships. It does not establish that content is safe to share. A redacted export is a new file, and the [safety rules](../spec/missing-data.md#safety) describe how to record its losses.

## Retain and delete together

Set a retention policy for source logs, uploaded exports, indexes and backups. Find a person's sessions through `user`, resolving changed identifiers through the directory when needed. Delete those exports or replace them with authorized redacted exports, then remove stale indexed text. Keep annotations in step by deleting or redacting facts and references affected by the same policy.

A native source deletion does not delete uploaded copies by itself. Reconcile those copies under the retention policy. The [tool-builder guide](../site/pages/get-started/tool-builders.mdx#updates-and-retention) covers replacement exports and deletion notifications.

## Report usage and cost

Join users to the directory to report usage and cost by team or cost center. Group cost by currency and keep estimates distinct from provider figures. Missing cost is unknown.

Follow the [usage rules](../spec/records.md#usage-and-cost). Sum original per-call figures once, excluding copied records. Show session totals separately. Never add child usage to a parent total that includes subagents or whose scope is unknown. Model settings and agent modes can explain differences between sessions without supplying values the source did not record.

For policy reports, use native `approval` and `sandbox` values and any `asks` summary in effect at the action's position. A policy change without `asks` makes the summary unknown. Keep a recorded `externalSandbox` alongside them. It describes a boundary outside the agent process, not a sandbox used only by some tools.
