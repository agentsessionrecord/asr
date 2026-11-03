# Database converters

These offline adapters read native SQLite snapshots in a read transaction. The
transaction includes committed WAL data. They never update the source database.
OpenClaw also accepts legacy session JSONL files. Output uses the same private
staging, secret filtering and record writer as the other converters.

```sh
asr convert --agent opencode /path/to/opencode.db --out /private/export
asr convert --agent goose /path/to/sessions.db --namespace example-profile --out /private/export
```

Goose needs a stable installation or profile namespace because its IDs are local
counters. Legacy Kiro conversations keyed by working directory also need one.
Keep that value stable when moving a database. Other adapters accept a namespace
when separate installations need one. Paths never become an installation ID.
Conflicting session IDs in different databases skip the conflicting session and
produce a named diagnostic. Independent sessions continue. Convert conflicting
stores separately with distinct namespaces.

## Supported storage profiles

The SQL files in `tests/fixtures/sqlite/` are authored native examples. Each
adapter has a validated golden file in `tests/golden/`. They contain no captured
history. Storage support describes the listed shapes. It does not promise
compatibility with every release of an agent.

| Agent | Native profile | Standard projections |
| --- | --- | --- |
| AstrBot | `conversations.content`, `provider_stats` in `data_v4.db` | Retained messages, calls, results and title |
| Crush | `sessions`, `messages.parts`, file snapshots | Messages, calls, results, summaries and session counters |
| Qoder CN (`lingma`) | `chat_record` | Prompt and shortened answer summary |
| Shelley | Sequenced `messages` with Go content variants | Messages, tools, per-call usage, copies and parent relationships |
| DeepAgents | LangGraph SQLite `writes` and `checkpoints` | Root message writes, message revisions, tools and usage |
| ForgeCode | `conversations.context.messages` | Text and reasoning, tools, output and cache usage subsets |
| OpenCode | Split `session`, `message`, `part`, plus sequenced `session_message` or `session_entry` | Messages, tools, usage, settings and recorded edits |
| Kilo | OpenCode-compatible SQLite tables | Same storage mapping as OpenCode |
| MiMoCode | OpenCode-compatible SQLite tables | Same storage mapping as OpenCode |
| Zed | Thread format `0.3.0`, JSON or Zstandard BLOB | Messages, tools, compaction, cumulative usage and subagent parent |
| Devin | `message_nodes`, `tool_call_state` | Retained messages, request IDs, result snapshots and structured file diffs |
| Firebender | `chat_sessions.messages_json` | Messages, calls, results and title |
| Goose | `messages.content_json` and `usage_ledger` | Messages, tools, output and cache usage subsets |
| Kiro | `conversations_v2` or legacy `conversations` | History entries, tools, request timing and retained summary |
| Warp | `agent_conversations`, protobuf `agent_tasks.task` | Selected message and tool variants, execution receipts and native IDs |
| OpenClaw | `session_windows`, `session_nodes`, sequenced `transcript_events`, optional approval store | Messages, response usage, tools, revisions, settings, explicit parents, decisions and changed edit receipts |

OpenCode profiles follow the 1.18.18 stored layout and the sequenced v2 shapes
described in `agents/opencode.md`. Kilo and MiMoCode support compatible layouts,
without claiming every fork release. OpenClaw follows `agents/openclaw.md`,
including compressed events and a separately ordered approval store. AstrBot's
profile is `data_v4`. Zed rejects versions other than `0.3.0`. Other profiles use
the table and JSON shapes shown by their SQL examples and are not version gates.

## Evidence and limits

Safe native data without a standard projection stays in an agent vendor record.
The header names the optional `<agent-domain>/native-sqlite` extension. Its
`<agent-domain>/event` records store native evidence under `_meta`.
The session header declares partial coverage for usage, model identity, settings,
approvals, tools, copies, commits, file changes, subagents, timestamps and order.
Some of those facts can be present while coverage remains incomplete. Mutable
snapshots do not establish their earlier states. Side tables and unordered branch
snapshots do not establish a single chronological audit trail.

Usage reports identify inference records only when the source identifies a call
or a distinct report. Session totals never become guessed calls. OpenCode uses
message usage only when no step report overlaps it. Goose, ForgeCode and Devin
keep unknown cache inclusion out of standard input totals. Their known output
and cache subsets remain available. AstrBot context size stays native metadata.

Distinct results with a reused call ID remain separate. Their native link moves
to metadata and `ambiguous_tool_results` records the loss. Revisions fold only
when native item identity establishes that they update the same item. Copied
records carry namespaced references when the source establishes ownership.

OpenClaw terminal approvals need a matching post-decision result receipt to get a
standard source position. Pending rows and unpositioned decisions remain native
evidence. A device resolver does not identify a person. Changed write or edit
receipts can establish application and a recorded creation flag establishes the
operation. Requested write content does not establish final bytes.

Unsupported nested conversations, provider settings, hooks and most commit
evidence stay in metadata. Firebender child snapshots and DeepAgents checkpoint
state do not become invented independent sessions. DeepAgents does not recursively
search checkpoint state for chat messages. The header declares `native_binary_fields` for incomplete binary coverage.
Undecoded binary payloads are omitted
because they can hide credentials. Warp declares `protobuf_fields` and
`model_facing_output`. Its display text stays in metadata. DeepAgents declares
`messagepack_binary_fields`. Opaque reasoning state is removed.

Rows are checked for byte size inside SQLite before allocation. Decoded compressed
payloads share the record size limit. Malformed or oversized rows create gaps
when their session is identifiable. Unsupported schemas, unidentified sessions
and empty databases produce diagnostic counts. Directories are scanned in stable
name order and symbolic link directories are not followed.

## Private corpus checks

Run the bounded sampler with only native history
roots. The limit is at most 100 files per agent and the combined conversion and
validation budget is at most 300 seconds per file.

```sh
python3 crates/asr-convert/scripts/check-databases.py \
  --binary target/debug/asr \
  --validator tools/validator/bin/asr-validate.js \
  --root opencode=/private/native \
  --out /private/qualification
```

Use `--namespace goose=example-profile` or `--namespace kiro=example-profile`
when needed. The sampler uses the shared size selection and subprocess deadline
helpers. It writes an owner-only catalog with source paths. Its count summary
contains opaque file IDs and per-agent diagnostic codes. Failed and timed out
outputs are removed. An empty native store is reported as `no_session` and is
not counted as a successful transcript check.

`scripts/ci.sh` runs the Rust integration tests, Python sampler tests and Node
validation of every golden file through its existing discovery rules.
