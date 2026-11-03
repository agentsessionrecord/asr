# Document converter samples

Every file here is synthetic. SQLite fixtures are SQL scripts so their rows can
be reviewed without a database viewer. The Rust tests create temporary databases
from those scripts. No agent runs or model calls are needed.

These profiles support the following source versions. An unversioned profile
means the native format supplies no version discriminator. Support covers the
listed fields and shapes. It does not claim every release of the client.

| Agent | Supported source version or profile | Input |
| --- | --- | --- |
| Auggie | Unversioned session document with `sessionId` and `chatHistory` | `auggie/session.json` |
| Cline | SDK message artifact version 1 and unversioned API task history arrays | `cline/sample.messages.json` |
| CodeBuddy | Unversioned CLI JSONL and extension `index.json` with `messages` | `codebuddy/session.jsonl` |
| Continue | Unversioned saved session with `sessionId` and `history` | `continue/session.json` |
| Hermes | Unversioned SQLite `sessions` and `messages` tables | `hermes/state.sql` |
| NanoClaw | V2 project database and per-session inbox and outbox tables | `nanoclaw/*.sql` |
| OpenHands | SDK event documents and legacy event files | `openhands/conversations/openhands-sample/events/*.json` |
| Roo Code | Unversioned API task history arrays with task metadata | `roo-code/tasks/task-sample/*.json` |
| Rovo Dev | Unversioned `message_history` with Pydantic message parts | `rovodev/session_context.json` |

Run `cargo test -p asr-convert --test documents` to compare exports with their
committed goldens and validate every output. Set `ASR_UPDATE_DOCUMENT_GOLDENS=1`
only when intentionally regenerating those goldens.

## Mapping rules

Native session fields supply identity. Cline and Roo task directories can supply
their documented task ID when metadata is absent. CodeBuddy extension directories
supply their session ID when an index and a messages directory establish the
storage shape. OpenHands conversation directories supply the native conversation
ID. An arbitrary input basename supplies no identity. Alias fields must agree.

Native array order and SQLite row order stay intact. OpenHands numeric event
filenames use numeric order. Independent NanoClaw mailboxes retain their own row
order and declare `cross_mailbox_order` as missing. Timestamps never sort records.
Cline display history stays as vendor evidence when API history is available.
Its snapshot cannot establish an order among the API actions.

Text is preserved, including whitespace and XML-like wrappers. Auggie text nodes
become ordered text parts without inserted separators. Unfamiliar nodes remain
vendor evidence. A user role alone supplies no human author. Assistant messages
supply model authorship. Ordinary messages and configured model labels supply
no inference boundary or served model. These adapters declare model and usage
losses and preserve unsupported model evidence in metadata.

Tool calls preserve native IDs, names and supplied arguments. Missing call IDs
are derived deterministically. The fixed tool-kind map is `Read` and `read_file`
for read, `Write`, `Edit`, `MultiEdit` and `apply_patch` for edit, `Bash`, `exec`,
`exec_command`, `shell`, `shell_command` and `local_shell` for execute, `Grep`,
`Glob`, `WebSearch` and `search` for search, `WebFetch` for fetch, and
`EnterPlanMode` and `ExitPlanMode` for switch mode. Other kinds stay absent.
A native tool-use block in an assistant message supplies `requestedBy: model`.
Saved tool-state snapshots alone supply no requester or approval decision.

Results use explicit source status. `success`, `succeeded`, `done`, `complete`
and `completed` map to completed. `error`, `failure` and `failed` map to failed.
`rejected` and `denied` map to denied. `canceled` and `cancelled` map to cancelled.
`interrupted` stays interrupted. A supplied `is_error` boolean distinguishes
failed from completed for native content blocks. Other statuses stay unknown.
Exit codes alone supply no status. Revisions of a result fold at its final
observation. Missing later status retains an earlier explicit status.

Hermes retains inactive and compacted rows. Its session totals and explicit end
are emitted after the retained messages. Hermes input totals add uncached input
to each supplied cache read and write count. Missing optional components stay
absent. Invalid or unknown supplied counts leave the input total unknown.
Hermes output already includes reasoning, so reasoning is not added again.
Actual USD cost is provider reported. Estimated USD cost is harness estimated.
Continue keeps reported prompt and completion totals in a tail `session_info`.
Neither adapter divides session totals into guessed model calls.

Known secrets and provider signatures are excluded. Redacted messages are marked
as truncated. Missing native history, unsupported normalized facts and binary
content are declared. Malformed complete JSONL records and over-limit SQLite
rows produce gaps when their session is known. An incomplete JSONL tail is
counted and deferred. A malformed or over-limit whole document produces a gap when metadata or a
documented storage directory identifies its session. Other unidentified inputs
are reported without inventing a header.
The default document and row bound is 16 MiB. Larger documents need a larger
explicit bound.

## Qualification

Run `scripts/check-documents.py` with `--binary`,
`--validator` and a private `--out` directory. Optional `--root agent=directory`
arguments add native roots. The sampler checks up to 100 files per agent and
shares a five-minute conversion and validation budget across that agent.
It uses the common size-stratified sampler and records counts for every agent,
including agents with no local history. Output is private and contains no
new model requests. A successful empty inventory establishes no live coverage.
