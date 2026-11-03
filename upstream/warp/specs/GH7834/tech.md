# Local saved-conversation export

## Context

The client repository is open source. Persistence is under AGPL-3.0.
`crates/persistence/src/model.rs:912` defines `AgentConversationRecord`.
`model.rs:959` pairs that record with decoded task snapshots.
`crates/persistence/src/agent_session.rs:12` in the reference patch exports one
saved task. The example at `examples/export_agent_session.rs:10` reads SQLite
in read-only mode. This snapshot lacks a complete lifecycle event stream.

## Proposed changes

Keep conversion in persistence, using its own task and message types.
Read source identity and times before writing the header. Build the text
projection before emitting any record so invalid input fails before output.
Use native message IDs and stringify wide IDs. Unsupported messages become gaps.
Declare missing tools, settings, usage, approvals and relationships in the header.
Do not interpret prose as file changes or model identity.

The example is a local reference entry point. A product integration should add
an `agent-session` choice to the existing conversation export flow once the
spec is accepted. It should write a private new destination file atomically.
It must not overwrite an existing file or expose output on an error.

Live hooks are outside this patch. A later hook design needs source-position
lifecycle events, permission decisions with call IDs, bounded backpressure,
secret handling and a policy for sink failures. It must not reconstruct these
facts from the saved-text projection or claim replay compatibility.

## Testing and validation

For invariants 1, 8 and 10, exercise explicit offline invocation against a copy
of a synthetic database and verify the source file remains unchanged.
For 2, 3 and 5, compare native IDs, times, text and gaps with the synthetic export,
then validate every record with the ASR validator.
For 4 and 6, cover multiple tasks and invalid times in persistence unit tests.
For 7, assert declared losses and absent invented fields.
For 9, use the upstream secret-redaction facility and built-in redaction patterns.
Test text and reasoning removal, truncation markers, declared loss, unchanged
source data and rejection before output for an identity or cwd match.
This policy excludes recognized secrets and does not discover arbitrary private
answers. A product export action still requires an accepted privacy policy.

Run persistence tests and targeted Clippy, then format the touched crate.
The example and packaged fixture must reproduce the same records.
Current results and implementation gaps are in the package's refresh metadata.
