# Native JSONL adapters

These adapters read local files through the shared converter framework.
They keep native observations in declared vendor records and project facts with
established meanings into ASR core records. They never start an agent, run a
recorded command or follow a recorded URI.

```sh
asr agents
asr convert --agent pi native-history --out private-output
asr convert --agent kimi-code native-sessions --out private-output
asr validate --summary private-output
```

Pass a native file or a directory. Directory discovery finds JSONL and Zstandard
JSONL files. A plain file takes precedence over its compressed companion.
Output files are private and replace earlier exports atomically.

## Source profiles and samples

The synthetic native samples live in `../../tests/fixtures/jsonl-b/`.
The exact ASR goldens live in `../../tests/jsonl-b/golden/`.
Release numbers below identify source evidence for a shape. They do not claim
compatibility with every version between releases. Several journals do not state
a release version. Their supported profile is defined by the listed fields and
the committed native sample. No wider release range is claimed for those profiles.

| Agent | Source version or profile | Identity |
| --- | --- | --- |
| `antigravity` | Trajectory transcript profile v1 | Conversation directory above `.system_generated/logs/transcript_full.jsonl` |
| `tabnine` | CLI 0.25.1 recording shape | Header `sessionId` |
| `qoder` | Unversioned `session_meta`, `user` and `assistant` journal profile | Recorded `sessionId` |
| `droid` | Unversioned `session_start` and `message` journal profile | Header `sessionId` or `id` |
| `copilot-cli` | CLI 1.0.104 event profile | `session.start.data.sessionId` |
| `qwen-code` | Unversioned UUID conversation journal profile | `sessionId`, or sidechain `agentId` |
| `grok-build` | Build 1.0.3 ACP notification shape and response boundary profile | Notification `params.sessionId` or `sessionId` |
| `pi` | Session JSONL versions 1 through 3 and mutation journal version 4 | Session header `id` |
| `kimi-code` | Wire protocol 1.5 event profile | Main agent uses native state `id`. Children use native agent ID within that session namespace |
| `deepseek-harness` | Logical session versions 0 and 4 | Session header `id` |
| `junie` | Unversioned `UserPromptEvent` and `SessionA2uxEvent` profile | Native `session-*` directory containing `events.jsonl` |
| `openclaw` | Legacy session JSONL archive profile | Session header `id` |

Kimi requires `sessions/<workdir>/<session>/agents/<agent>/wire.jsonl`.
It requires the native session `id` from bounded `state.json` or
`session-meta/state.json`. Arbitrary directory names never supply identity.
The main agent uses that ID without a namespace. Child agent IDs use the native
session ID as their namespace and explicit `parentAgentId` for parent links.
Main-agent `forkedFrom` names a native fork. Copy boundaries remain unavailable
and `copies` stays declared missing. Other wire protocol versions are rejected.
Junie requires its native session directory. Antigravity selects the full
transcript when both full and partial transcripts exist.
DeepSeek selects the newest committed `session.vN.jsonl` generation in a directory.
Its compressed generation names follow the same selection rule.
A filename never supplies an identity for a self-identifying journal.

The OpenClaw adapter reads JSONL archives. It does not read the current
2026.10.7 SQLite store, approval database or collection manifests.
The current OpenClaw converter notes still govern shared field meanings.

## Core mappings

Droid and Qoder split native text, `tool_use` and `tool_result` blocks.
They keep native tool IDs and names. Assistant messages establish model authorship.
A user role alone does not establish human authorship. No inference comes from
an ordinary assistant message in those journals.

Copilot joins tool requests with execution starts and folds result updates.
Distinct execution starts that reuse an ID remain separate calls.
Embedded `agentId` events produce separate namespaced child streams.
Native `apiCallId` identifies a model call. Usage updates complete that inference.
The native input counter has unknown cache inclusion, so it stays in metadata.
Known output counts and cache subsets retain their recorded zeros.
Explicit permission completions produce approvals at their own source positions.
A reused grant needs explicit policy evidence before it can name a person.

Kimi uses context appends as delivered messages. Prompt acceptance remains vendor
evidence. Request attempts identify inferences. Step completion folds the last
attempt with its usage at the completion position. Completed `content.part` observations retain their own UUID and source position.
Intervening events remain in order. Readable reasoning stays exact and encrypted
reasoning produces a separate content-free marker. Malformed complete lines and
incomplete tails produce positioned gaps.
Persisted tool output lacks the final model rendering and stays in metadata.
Explicit origin fields can establish human, hook or harness authorship.

Grok joins adjacent compatible text chunks. Prompt and message IDs bound assembly.
Tool updates fold at their final contributing observation. UI tool output stays
in metadata. Only explicit response boundaries establish inferences.
A completion can supply a provider ID that was missing at the start.
References are updated to that ID without moving intervening records.

Pi and OpenClaw keep message parts, reasoning, tool arguments and recorded outcomes.
A requested `model` never supplies the served model. `responseModel` supplies the
served model when recorded. A native response ID establishes an inference.
Pi v4 usage ledger records also identify calls. Input usage includes supplied
cache reads and writes. Output usage already includes reasoning.
Legacy assistant usage without a response ID remains vendor evidence.
Unavailable or placeholder usage stays unknown. Recorded zero counts stay zero.
OpenClaw user display text stays in metadata when no model prompt projection exists.
Retained tool definitions become offered tools at their checkpoint position.

DeepSeek keeps surface messages, native provenance and calls. Its request header
supplies recorded instructions, offered tools and request settings.
Finish events and assembled step responses identify model calls.
A native copied seed marks copied records with their parent session reference.
Compaction replacement summaries do not become ordinary human prompts.

Tabnine keeps the final snapshot of each native message ID. Tool results keep
recorded status while raw output stays in metadata. Per-message token counters
lack a proven call boundary and remain vendor evidence.
Antigravity keeps rendered trajectory content in vendor evidence. A planner
response can carry recorded reasoning. Its text does not establish API context.
Junie keeps prompt events without guessing their author. Native step IDs identify
derived calls. File snapshots keep full recorded before and after text with
unknown application status.

## Fixed tool kinds

The adapters use the shared fixed tool map and these additional native names.
They never derive a kind from argument or output text.

| Names | Kind |
| --- | --- |
| `read`, `ReadFile`, `view` | `read` |
| `write`, `edit`, `create`, `Create`, `ApplyPatch`, `str_replace` | `edit` |
| `Execute`, `run_shell_command`, `bash`, `bashExecution` | `execute` |
| `web_fetch` | `fetch` |
| `web_search` | `search` |

A Grok native ACP kind is retained verbatim. No tool name is guessed from a title.
No approval is guessed from a tool outcome, exit code or mode.
No file edit is declared applied from a request alone.

## Limits

Every header declares partial capture. Unmapped usage, costs, approvals,
file changes, commits, copies, settings and tool definitions remain declared
losses even when some evidence in that category is captured.
Unsupported observations remain searchable in vendor records after filtering.
Vendor preservation does not establish normalized accounting or blame support.
Sidecar joins beyond Kimi state, external output files, telemetry and complete
copy detection are unsupported. Junie index snapshots are not read.
Pi parent paths are retained without following them. Grok turn totals and
Qwen usage counters remain vendor evidence when their scope is not established.

The record limit bounds each native line and assembled record. Oversized and
malformed complete lines produce gaps. Incomplete tails are deferred and counted.
A size limit can shorten an assembled message or replace an oversized projection
with a gap. These losses are declared. Credentials, explicitly secret answers,
provider signatures and opaque reasoning state are excluded.
Core counts outside the safe integer range are omitted while exact native values
remain strings in vendor metadata. An invalid cache count also leaves its inclusive
input total unknown. These streams still need private handling.

## Checks

```sh
cargo test -p asr-convert --test jsonl_batch_b
cargo test -p asr-cli --test jsonl_b
node tools/validator/bin/asr-validate.js --summary crates/asr-convert/tests/jsonl-b/golden
```

Run commands from the repository root.
The tests compare exact goldens and check source facts independently.
They cover folding, child streams, source identity, conservative authorship,
usage arithmetic, compression, copies, malformed input, null input and secrets.
The root CI runs these tests and validates every batch golden.

For private history checks, use `../../scripts/check-sample.py` with `--limit 100`
and `--timeout-seconds 300`. Keep its output outside the repository.
Real history qualification and running a new agent are separate results.
All adapters remain marked as not live-tested until a new agent run is checked.
