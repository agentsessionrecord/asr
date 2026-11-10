---
title: "Codex"
description: "Converter notes for Codex rollout logs."
---

Codex rollout logs convert to Agent Session Record (ASR) with the [shared mappings](index.md#shared-mappings) and the rules below. Unmapped native fields can go in `_meta` under `com.openai.codex`.

## Logs and format

Use `producer.source: "codex-rollout"`. JSONL rollouts live under `~/.codex/sessions/YYYY/MM/DD/rollout-<timestamp>-<thread id>[_<rollout id>].jsonl`, and one thread can span several segments. Inactive files may be compressed as `.jsonl.zst` or moved under `archived_sessions/`. Resolve aliases before identifying segments.

## Session identity

Use the thread's own `session_meta.id`, which stays the same across segments. A child can also contain its parent's metadata, and the spawn tree's root `session_id` does not identify a thread. No `namespace` is needed. Take a torn header's ID from the file name only when the native thread index confirms it.

## User and settings

`creator_user_id` supplies `user.id` with `source: agent_account`. `creator_account_id` does not identify a person, so keep it as account context in the header's `_meta`. Native email and name fields are not covered.

`turn_context.effort` supplies `inference.settings.reasoningEffort` for established calls in that turn, and a recorded turn `service_tier` supplies `serviceTier`. `thread_settings_applied.thread_settings.reasoning_effort` and `service_tier` are configured `agentSettings.modelSettings`, not call settings. Temperature and output token limit are not documented.

The turn's `approval_policy` and `sandbox_policy` supply `agentSettings.approval` and `sandbox`, including structured policies, and `thread_settings_applied.thread_settings` also records changes. Keep `collaboration_mode`, `approvals_reviewer` and unfamiliar permission-profile details in `_meta` unless a supported mapping gives them a core meaning.

`session_meta.dynamic_tools` and retained `additional_tools` items record tool definitions. Map names, descriptions, input schemas and namespaces to `session_info.tools`, with the namespace as `source`. Declarations can be incremental, so carry the known union at each update and list `tools` in `missing` when the list is partial. A `tools.removed_definition` notice does not name the removed tools. If removals cannot be resolved, keep the definitions in `_meta` and leave the offered list unknown, without rebuilding definitions from calls. `base_instructions` and captured developer instructions become messages with role `system` or `developer` and `origin: instructions`.

## Record and call IDs

`call_id` supplies `callId`, `turn_id` supplies `turnId` and `token_usage_record.response_id` the inference ID. Derive other IDs from the segment, the ordinal or physical line, and a sub-slot. Record only established segment order.

Assistant `payload.phase: commentary` maps to `commentary` and `final_answer` to `final`. `content_item_kinds` lines up with message parts and gives authorship per part. `user.text` and `user.image` are human prompts. `agents_md.instructions`, `environments.environment_context`, `permissions.instructions`, `collaboration_mode.instructions` and `host_skills.instructions` come from the harness, and `hooks.additional_context` from a hook. `multi_agent.subagent_notification` is `author: agent` with `origin: subagent_report`, with `from` only when the sending thread is known. XML-like markers in the text do not establish authorship.

For reasoning with a summary and `encrypted_content`, keep the summary as `summary: string[]` with `visibility: summary` and drop the encrypted bytes. With only encrypted content, use `visibility: encrypted` and no content. Keep a recorded empty summary array.

`function_call`, `custom_tool_call` and `local_shell_call` use `requestedBy: model`. A nested code-mode `CommandExecution`, `McpToolCall` or `FileChange` uses its invocation item ID and `requestedBy: code`. `CommandExecution.source: user_shell` means `user`. Only an explicit ID of the initiating model call supplies `parentCallId`, and a `cell_id` does not.

## Subagents and parents

`source.subagent.thread_spawn.parent_thread_id` and `agent_role` give a subagent's parent and role. `forked_from_id` and `forked_from_ordinal_exclusive` give a fork and its boundary. `history_base.thread_id` names a rollout segment, so resolve the thread that owns it first. A revert within one thread stays in the same stream.

Under the native copied-prefix contract, `subagent_history_start_ordinal` can establish `copiedThrough`. A child with both delegation and fork facts uses the subagent parent and keeps the fork detail in `_meta`.

## Tool kinds and file edits

Map `apply_patch` and `FileChange` to `kind: edit`, `exec_command` and `CommandExecution` to `execute`, and `update_plan` to `think`. A `request_user_input` call uses `other`, with the question in the call input and the person's recorded answer in the result, when the rollout keeps both. A request notification alone has no answer. Other tools leave `kind` absent.

A `custom_tool_call` for `apply_patch` stores the patch in `payload.input`, kept as `inputText`. This patch language is not a unified diff. `*** Add File`, `*** Update File`, `*** Delete File` and `*** Move to` give the paths and requested operations. Decode exact update hunks into `edits` without inventing positions, or keep only file activity if decoding is uncertain. Add File content can supply `after.text` when its bytes are established. Join `custom_tool_call_output` through `call_id`. A matching `patch_apply_end` with `success: true` establishes application, folded with the output into one result. A request alone stays `proposed`.

Completed `FileChange.changes` entries are keyed by path. `type: add` and `delete` carry full `content` for `after.text` and `before.text` respectively, and `type: update` carries `unified_diff` as `patch`. A `move_path` is the destination, with the map key as `oldPath`. Successful completion establishes `applied`. Progress updates can hold empty delete placeholders or custom hunks, so they establish neither full contents nor unified patches. Fold results at the final contributing observation under the [ordering rule](../spec/format.md#file-format-and-order).

## Commits

For `exec_command`, keep `cmd` and `workdir` from the arguments and read commit output from the linked execution outcome. Keep a structured `exit_code` only when recorded. Legacy model-facing shell text does not establish a numeric exit code. PR attachments become `pr_link` with `reported` evidence.

## Token usage and cost

In `token_usage_record.usage`, the inclusive `input_tokens` and `output_tokens` map to `inputTokens` and `outputTokens`. Supplied `cached_input_tokens`, `cache_write_input_tokens` and `reasoning_output_tokens` map to `cacheReadTokens`, `cacheWriteTokens` and `reasoningTokens` and are not added again. Keep recorded zeros. `total_tokens` goes in `_meta`, outside both totals.

In a recorded `token_count.info.total_token_usage`, `input_tokens` and `output_tokens` map directly to session totals, and a supplied `cached_input_tokens` to `cacheReadTokens`. Each repeated total replaces the last, and none becomes a per-call inference.

`turn_context.model` supplies the requested model, and usage records do not name the served one. A recorded `response_id` still establishes an inference without a turn model, so omit `model` and declare the loss. Cost is not recorded.

## Missing data

List `model` when the served model is absent, `usage` when call accounting is unavailable, `copies` when inherited boundaries cannot be resolved and `agent_settings` when policy snapshots are unavailable. Compaction summaries use `origin: compaction`, with a `gap` where history was lost. Opaque reasoning bytes are left out.

## Approvals and agent settings

Ordinary rollouts discard structured approval requests, resolutions and automatic-review events. Import `codex.tool_decision` telemetry as approval records joined by `call_id`, or list `approvals` in `missing`. Its `decision` is opaque and needs a decoder for each version.

In 0.144.3 through 0.163.0 the decision strings decode as follows, with the native value kept in `native`.

| Native decision | `decision` | `scope` |
|---|---|---|
| `approved` | `approved` | `once` |
| `approved_for_session` | `approved` | `session` |
| Established persistent policy amendment | `approved` | `always` |
| `denied`, `abort` | `denied` | |
| `timed_out` (unanswered) | `cancelled` | |

Set `by: user` only when the recorded decision source establishes a person's answer, `policy` for a `Config` decision or established grant reuse, and `classifier` for `AutomatedReviewer`. `Config` alone cannot establish `hook`, and a current policy file cannot establish any per-call decision.

For ordinary policies with human review, `never` supplies `asks: never`, while `on-request` and `untrusted` supply `asks: sometimes`. Granular profiles, automatic review and per-call overrides can change whether a person is asked, so omit `asks` when the snapshot cannot establish it. An external sandbox declaration stays separate from the native policy.

A saved `external-sandbox` supplies `externalSandbox.source: setting` and the native policy. It does not establish a container or VM kind, and its declared `network_access` does not prove how the outer boundary is configured.

## Triggers, hooks and storage

| Area | What the rollouts keep |
|---|---|
| Triggers | The native `source` distinguishes clients and subagents. Schedule, webhook and channel origins are not documented. `exec` does not establish a scheduled run |
| Hooks | `hook_started` and `hook_completed` are not durable rollout events. Permission hooks report as `Config` in decision telemetry |
| Store changes | The recorder appends and flushes JSONL. Resolve segments, compression and archived files before conversion |
| Pruning | Ephemeral sessions are not saved. The rollout is selected history, and tool outputs can be truncated |

## Source versions

These mappings describe rollouts from 0.144.3 through 0.163.0. Samples should include the execution notifications that establish application. The [0.163.0 sample](https://github.com/agentsessionrecord/asr/tree/main/samples/codex) pairs a synthetic native rollout with its export and file digests. Tool retention, token members and completed file endpoints follow the [rollout policy](https://github.com/openai/codex/blob/ff2346f33f851bd4e90c8e42ae60abcc7e7f293b/codex-rs/rollout/src/policy.rs), [protocol](https://github.com/openai/codex/blob/ff2346f33f851bd4e90c8e42ae60abcc7e7f293b/codex-rs/protocol/src/protocol.rs) and [patch conversion](https://github.com/openai/codex/blob/ff2346f33f851bd4e90c8e42ae60abcc7e7f293b/codex-rs/core/src/apply_patch.rs). Approval, trigger, hook and storage details follow the [rollout policy](https://github.com/openai/codex/blob/275a9a89b6/codex-rs/rollout/src/policy.rs), [protocol](https://github.com/openai/codex/blob/275a9a89b6/codex-rs/protocol/src/protocol.rs) and [telemetry](https://github.com/openai/codex/blob/275a9a89b6/codex-rs/otel/src/events/session_telemetry.rs), checked October 30, 2026.

## Worked example

This synthetic rollout records a patch and its successful completion. Derived ASR IDs use the physical line and a sub-slot. The rollout has no model calls, served model, reasoning or event times, and `missing` says so.

```jsonl native
{"type":"session_meta","payload":{"id":"example-codex"}}
{"type":"response_item","payload":{"type":"custom_tool_call","call_id":"edit-1","name":"apply_patch","input":"*** Begin Patch\n*** Update File: /work/parser.py\n@@\n-limit = int(value)\n+limit = int(value or \"0\")\n*** End Patch"}}
{"type":"response_item","payload":{"type":"custom_tool_call_output","call_id":"edit-1","output":"Success. Updated files:\nM /work/parser.py\n"}}
{"type":"event_msg","payload":{"type":"patch_apply_end","call_id":"edit-1","success":true,"status":"success"}}
```

The ASR stream is:

```jsonl
{"type":"session","id":"header","formatVersion":"0.1","agent":{"name":"codex"},"sessionId":"example-codex","producer":{"name":"example-converter","version":"1.0","method":"converter","source":"codex-rollout"},"missing":["usage","model","reasoning","timestamps","approvals","agent_settings"]}
{"type":"tool_call","id":"line:2:call","callId":"edit-1","name":"apply_patch","kind":"edit","requestedBy":"model","inputText":"*** Begin Patch\n*** Update File: /work/parser.py\n@@\n-limit = int(value)\n+limit = int(value or \"0\")\n*** End Patch"}
{"type":"tool_result","id":"line:3:result","callId":"edit-1","status":"completed","content":[{"type":"text","text":"Success. Updated files:\nM /work/parser.py\n"}]}
{"type":"file_change","id":"line:4:change","callId":"edit-1","path":"/work/parser.py","op":"modify","status":"applied","edits":[{"oldText":"limit = int(value)\n","newText":"limit = int(value or \"0\")\n"}]}
```

## Native export

The [Codex export patch](https://github.com/agentsessionrecord/asr/blob/main/upstream/codex/README.md) adds `/export --format agent-session PATH` for saved local rollout history, with Markdown still the default. Codex does not accept outside code, so the patch is design feedback only.
