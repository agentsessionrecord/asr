# Approvals, policy and collection

The [session](approvals-and-policy.jsonl) uses a fictional agent. A scheduled
prompt has a recorded human author and sender. A different person answers a
tool approval and later sends an external message.

Two approval records precede the first result. A remembered session
grant supplies `by: policy`. A person then approves a sandbox escape once,
with `subject` naming that request. Completion is a separate recorded tool
outcome. The second call is denied by an unattended
fallback. The stream still lists `approvals` in `missing` because the exporter
cannot establish that it captured every decision.

The initial settings record `asks: sometimes` inside a recorded container.
`policy-change` supplies `asks: never` and changes the configured reasoning
effort while keeping the known temperature. `sandbox-change` records a native
boolean policy without `asks`, so the summary becomes unknown. The inference
has no call settings, even though the session has configured ones.
`boundary-cleared` clears the outer boundary with an empty object. Its empty
`modelSettings` changes nothing. The initial `tools` list records the definition
offered to the model.

The [redacted copy](approvals-redacted.jsonl) removes prompt text. Its
`derivedFrom.sha256` hashes the exact original ASR bytes. `missing` and
`truncated` still describe the loss. Every record is retained, so no gap is
needed in this copy. Its producer identifies the redactor as a converter.
The original producer is recoverable from the file `derivedFrom` names.

The [collection manifest](collection.manifest.json) is a separate JSON document
written by a fictional collector. Its entry has the exact original file's
SHA-256 and byte length. The first window has `previousManifest: null`. A later
window would link to this manifest's exact bytes, including a window with no
entries. The tests verify these byte relationships without treating them as
proof of the fictional session's truth.

See [Using ASR for audits](../guides/audits.md) for evidence limits and collection
guidance.
