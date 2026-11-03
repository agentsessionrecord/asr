# Transcript and snapshot adapters

These adapters use the converter API described in [README.md](README.md).
Run `asr convert --agent NAME INPUT --out OUTPUT`.
Input is a native file or a directory containing the supported layout.
Output remains private and uses one file per native session.

| Agent | Supported source contract | Synthetic sample |
| --- | --- | --- |
| `cursor` | Cursor CLI 2026.06.24 agent transcripts | [Cursor](tests/fixtures/w1-conv-a/cursor) |
| `gemini-cli` | Unversioned chat journal metadata and message objects, `$set`, `$rewindTo`, and legacy whole-document JSON | [Gemini CLI](tests/fixtures/w1-conv-a/gemini-cli) |
| `mistral-vibe` | Legacy v1 `meta.json` and `messages.jsonl`, plus `mistral.vibe.unified-session-store/v1` through minor 10 | [Mistral Vibe](tests/fixtures/w1-conv-a/mistral-vibe) |
| `mux` | Mux v0.27.0 chat messages, archives and partial files | [Mux](tests/fixtures/w1-conv-a/mux) |
| `fx` | `event_log_v1` with envelope schema 1 and history tool snapshots | [fx](tests/fixtures/w1-conv-a/fx) |

Source compatibility is limited to these contracts and their tested fields.
An unversioned contract does not establish the installed application's version.
The test suite also authors unified generations and fx replacements in temporary
directories. Every generated stream is checked by the Node validator.

## Cursor

The native identity is the storage key in
`projects/PROJECT/agent-transcripts/SESSION/SESSION.jsonl`.
An unrelated filename cannot supply an identity.
User and assistant records use nested `message.content` blocks.
Only an assistant `tool_use` establishes a model request.
Conflicting roles and unsupported records remain vendor evidence.
Turn summaries become harness notices.
Explicit timestamps are preserved. Dates embedded in text stay text.
The adapter does not assert human authorship from a user role.

Calls retain their names and arguments. No name-to-kind map is applied.
Tool outcomes come only from a supplied `is_error` value.
Absent outcome evidence stays `unknown`.
IDE databases, blob stores and external output files are outside this mapping.
These limits are declared in `missing`.

## Gemini CLI

Metadata `sessionId` supplies the native identity.
A migrated `.jsonl` takes precedence over its `.json` sibling.
Legacy JSON is read as a bounded snapshot.
Subagent metadata and the native `chats/PARENT/CHILD` layout can establish a parent.
Project hashes and filename times cannot establish a session identity.

Repeated message IDs are snapshots and fold at the final observation.
Rewinds preserve previously observed work.
A membership snapshot adds a gap for unavailable prior history.
Its source representation remains vendor evidence.
The adapter supports complete saved messages and does not interpret undocumented
streaming delta formats.

A token report attached to an assistant response establishes an inference.
Its ID is derived from the message ID. Stored `model` stays requested.
Input tokens include cached tokens. Output tokens add the optional thought count.
An absent thought count adds nothing. An invalid supplied thought count leaves
the inclusive output total unknown.
Unsafe counts remain exact strings in vendor evidence and `usage` stays in `missing`.

`replace` and `write_file` map to `edit`, `read_file` to `read`, and
`run_shell_command` to `execute`. Other kinds remain absent.
The call's `args` supply input. Model-facing results supply result content.
Display data stays separate in vendor evidence.
Recorded display file paths, diffs and complete new contents can supply file changes.
Only native success establishes an applied edit.
An empty fallback original is not promoted to a full before-state.
Masking is recognized only inside `functionResponse.response.output`.
Sibling media remain available. Ordinary transcripts establish no approvals.
Commit-output parsing is outside this mapping and `commits` remains declared missing.

## Mistral Vibe

Legacy identity comes from `meta.json.session_id`.
The starting directory and session times come from explicit metadata.
A parent ID with no relationship kind stays vendor evidence.
Tool arguments retain their native JSON string or JSON value representation.
Legacy tool results have unknown status unless cancellation is recorded.
A manual shell operation is requested by the user.
Its exit code does not establish its outcome.
Compaction summaries receive harness authorship and a following gap.

Unified stores verify `CURRENT`, manifest identity and component digests.
Only the selected generation is read. Chunk paths must stay within their store.
Checkpoint messages and tool requests receive core mappings.
The model-facing form of checkpoint tool output is unavailable and stays missing.
Recovery and projection state remain vendor records.
The adapter declares `recovery_projection` because it does not replay the recovery journal.
Snapshot settings are not applied retroactively to earlier actions.
Prompt totals whose cache inclusion is unknown stay in vendor metadata.
Recorded completion totals and cache components can supply session totals.
These snapshots do not create per-call inference records.

## Mux

Recorded `workspaceId` or the native `sessions/WORKSPACE` storage key supplies identity.
Conflicting recorded identities are rejected with `ambiguous_source_identity`.
Archive rows precede active rows. A staged partial replaces a matching history
sequence only when it has more parts. Unselected partials stay vendor evidence.
Repeated dynamic tool snapshots fold by native call ID.
Nested calls preserve `parentCallId` and `requestedBy: code`.
Native failure establishes failure. Output availability alone leaves status unknown.
Raw tool output can differ from the model-facing result, so it stays in metadata.
Compaction adds a summary and a gap.
Message usage can span several model steps and is retained without an invented scope.
No inference is synthesized from a message or model label.
Archive ownership does not establish who spawned a child.

## fx

`authority.json` supplies identity. The first event must agree with it.
The adapter freezes exactly the byte prefix named by the generation's commit file.
Sequence numbers, generation IDs, event IDs, final byte boundary and final event
must agree with the watermark. Pending authority or commit transitions are refused.
The authority and watermark are checked again before output.
Uncommitted tails are ignored.

Committed replacements verify chunk order, lengths and SHA-256 digests.
Encoded replacement bytes are omitted and marked as shortened vendor evidence.
Decoded states pass through secret filtering.
Previously observed work stays in source order when a replacement discards it.
Exact unchanged history entries at the same snapshot position are not counted twice.
Turn snapshots do not borrow a commit timestamp for their messages.
Tool statuses use native success and failure values.
File evidence supplies touch records without invented patches or contents.
Native permission state does not establish approval decisions.
Input totals with unknown cache inclusion stay in metadata.
This adapter checks commit boundaries and replacement integrity, rather than every
application-level condition enforced by the native reducer.
Legacy snapshot migration, conversation artifacts and external output replay files
are outside this source contract.

## Bounds and losses

Source lines and assembled records use the configured record bound.
Whole JSON documents and decoded replacement states must fit that bound.
An invalid or oversized sidecar refuses conversion before completed files are replaced.
Malformed complete JSONL lines produce gaps. Incomplete tails are deferred.
Directory traversal is deterministic and does not follow directory symlinks.
Zstandard transcript companions are supported where the native adapter uses JSONL.

All adapters declare partial capture for usage, served models, copies, approvals,
settings, offered tools, file changes, commits, subagents and timestamps.
Available facts remain usable alongside these declarations.
Unknown native observations remain under the agent's declared metadata domain.
Known secrets and opaque provider state are excluded.
Only synthetic data belongs in the repository.
