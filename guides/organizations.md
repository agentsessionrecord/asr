---
title: "Running ASR across a company"
description: "Collect sessions, identify their users and manage shared storage and reporting."
---

A company can collect Agent Session Record (ASR) files from every engineer's machine into shared storage, then search and report on them whichever agent produced them. [Using ASR for audits](audits.md) covers evidence limits, approvals and collection receipts.

## Collect on each machine

On a schedule, run a converter, exporter or an agent's own [export command](integration.md#export-command-convention) on each machine. Select sessions changed since the last successful collection, validate the exports and upload one file per session. The [`asr collect`](../site/pages/tools/collect.mdx) tool finds supported native logs, converts changed sessions and stores their exact bytes.

Upload a re-export as a complete file and update that session's index. A retried upload replaces the stored session rather than adding a second copy of its usage. Keep failed uploads for retry and report source files that can't be read. An audit store can also keep every received version in a [collection manifest](audits.md#write-a-collection-manifest) while its search index shows only the latest.

## Identify the person

Set the header's `user` from the agent account or the Git identity. A company exporter can supply a directory ID with `source: "configured"`. Prefer a stable ID, since email addresses and display names change and can be shared. Record where the identity really came from, and leave out facts that source doesn't supply.

```jsonl
{"type":"session","id":"header","formatVersion":"0.1","agent":{"name":"com.example.coder"},"sessionId":"session-42","producer":{"name":"company-export","version":"1.0","method":"converter","source":"example-jsonl"},"user":{"id":"engineer-42","email":"alex@example.com","name":"Alex Rivera","source":"configured"},"_meta":{"com.example.company":{"team":"developer-tools","costCenter":"engineering"}}}
```

`user` says who ran the session as the source or machine knew them. It is a grouping and access label, not proof of who wrote a prompt or made a commit. Authenticate the uploading exporter and check how it assigns identities before using the label for access decisions.

## Team and cost-center labels

An exporter can add team, department or cost-center labels under the company's own reverse-DNS key in `_meta`, as in the example. The company defines them, much like OpenTelemetry resource attributes.

Joining `user.id` to the company directory at query time is usually better, because an engineer can move teams without rewriting every session file. Labels in `_meta` are snapshots that can drift from the directory. A report should say whether it uses current membership or membership at the time of the work.

## Storage keys

One possible object key is `<user>/<agent>/<encoded-session-reference>.jsonl`. Encode each part safely and never treat a native ID as a path. A stable directory ID keeps email addresses out of object names. Session and user identity come from the records, not the path.

Deduplicate by the complete session reference, which includes the agent name, so a session uploaded through two collectors stays one session. Add `namespace` only when native session IDs repeat across installations, and keep it stable. Store annotations beside the exports or in a separate collection joined by their target references.

## Access and retention

Sessions hold prompts, code and command output, and their identity fields are personal data. Limit access by person and repository, including sessions that touch several repositories, and apply the same limits to search results, previews, downloads and derived indexes. Exclude known secrets before upload. A file that validates isn't necessarily safe to share, and a redacted export is a new file under the [safety rules](../spec/missing-data.md#safety).

Set one retention policy for source logs, uploaded exports, indexes and backups. To remove a person's sessions, find them through `user`, resolving changed identifiers through the directory, then delete the exports or replace them with authorized redacted ones, remove stale indexed text, and delete or redact the affected annotations. Deleting a native session doesn't delete uploaded copies, so reconcile those under the policy too. The [tool-builder guide](../site/pages/get-started/tool-builders.mdx#updates-and-retention) covers replacement exports and deletion notifications.

## Usage, cost and policy reports

Join users to the directory to report usage and cost by team or cost center. Group cost by currency, keep estimates apart from provider figures, and treat missing cost as unknown. Follow the [usage rules](../spec/records.md#usage-and-cost): sum original per-call figures once, excluding copied records, show session totals separately, and never add child usage to a parent total that includes subagents or whose scope is unknown.

For policy reports, use the native `approval` and `sandbox` values, any `asks` summary and any `externalSandbox` in effect at each action's position. The audit guide explains [how to read them](audits.md#policy-and-settings).
