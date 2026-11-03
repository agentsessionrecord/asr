---
title: "Codex"
description: "Converter notes for Codex rollout logs."
---

These notes describe `codex`. Native details without a core field can use `_meta` under `com.openai.codex`.

## Logs and format

Use `producer.source: "codex-rollout"`. JSONL rollouts live under `~/.codex/sessions/YYYY/MM/DD/rollout-<timestamp>-<thread id>[_<rollout id>].jsonl`. Threads can span segments. Inactive files may be compressed as `.jsonl.zst` or moved under `archived_sessions/`. Resolve aliases before identifying segments.

## Session identity

Use the thread's own `session_meta.id`, unchanged across segments. A child can contain parent metadata too. The spawn tree's root `session_id` does not identify each thread. No namespace is needed for the described IDs. Recover a torn header from the basename only when the native thread index corroborates it.

## User and settings

Recorded creator identity `creator_user_id` supplies `user.id` with `source: agent_account`. Keep `creator_account_id` as account context under `com.openai.codex` in header `_meta`. It does not identify a person by itself. Native email and name fields are not documented here.

`turn_context.effort` supplies `inference.settings.reasoningEffort` for established calls in that turn. Recorded turn `service_tier` supplies `serviceTier` where present. `thread_settings_applied.thread_settings.reasoning_effort` and `service_tier` instead supply configured `agentSettings.modelSettings`. Do not promote that session snapshot to call settings. Temperature and output token limit fields are not documented.

The turn's `approval_policy` and `sandbox_policy` supply `agentSettings.approval` and `sandbox` verbatim, including structured policies. `thread_settings_applied.thread_settings` also records changes. Emit `session_info` at each established change before the affected records. Preserve `collaboration_mode`, `approvals_reviewer` and unfamiliar permission-profile details in `_meta` unless a supported mapping establishes their core meaning.

`session_meta.dynamic_tools` and retained `additional_tools` items supply recorded tool definitions. Map names, descriptions, input schemas and recorded namespaces to `session_info.tools`, using the namespace as `source`. Additional declarations can be incremental, so retain their known union at each update and list `tools` in `missing` when the catalog is partial. A `tools.removed_definition` notice does not provide a structured list of removed names. If removals cannot be resolved, keep definitions in `_meta` and leave the offered list unknown. Do not reconstruct definitions from calls. Record `base_instructions` or captured developer instructions as messages with the corresponding `system` or `developer` role and `origin: instructions`.

## Record and call IDs

Use `call_id` as `callId`, `turn_id` as `turnId` and `token_usage_record.response_id` as the inference ID. Derive other IDs from segment identity, ordinal or physical line, and a sub-slot when splitting items. Record only established segment order.

Map assistant `payload.phase: commentary` to `commentary` and `final_answer` to `final`. `content_item_kinds` aligns with message parts. `user.text` and `user.image` identify human prompts. `agents_md.instructions`, `environments.environment_context`, `permissions.instructions`, `collaboration_mode.instructions` and `host_skills.instructions` identify injected harness parts. `hooks.additional_context` identifies a hook. `multi_agent.subagent_notification` identifies `author: agent`, `origin: subagent_report`. Use part-level overrides. Do not infer authorship just from XML-like text markers. Set `from` only when the sending thread is known.

For reasoning with a summary and `encrypted_content`, keep the summary as `summary: string[]` with `visibility: summary` and discard encrypted bytes. With only encrypted content, use `visibility: encrypted` without content. Preserve a recorded empty summary array.

`function_call`, `custom_tool_call` and `local_shell_call` use `requestedBy: model`. A nested code-mode `CommandExecution`, `McpToolCall` or `FileChange` uses its invocation item ID and `requestedBy: code`. `CommandExecution.source: user_shell` means `user`. Only an explicit initiating model-call ID supplies `parentCallId`. A `cell_id` does not.

## Subagents and parents

`source.subagent.thread_spawn.parent_thread_id` and `agent_role` identify a subagent's parent and role. `forked_from_id` and `forked_from_ordinal_exclusive` identify a fork and boundary. `history_base.thread_id` names a rollout segment, so resolve its owning thread first. A same-thread revert stays in the same stream.

Under the native copied-prefix contract, `subagent_history_start_ordinal` can establish `copiedThrough`. A child with both delegation and fork facts uses the subagent parent and keeps extra fork detail in `_meta`. Never detect copies by text similarity.

## File-edit evidence

Map `apply_patch` and `FileChange` to `kind: edit`, and `exec_command` or `CommandExecution` to `execute`. Map `update_plan` to `think`. A retained `request_user_input` call uses `other`, with the question in the call input and the person's recorded answer in the result. These mappings apply when the rollout retains the function call and output. A request notification alone does not supply an answer. Other tool names need a documented map or keep `kind` absent.

A `custom_tool_call` for `apply_patch` stores the patch language in `payload.input`, retained as `inputText`. `*** Add File`, `*** Update File`, `*** Delete File` and `*** Move to` establish paths and requested operations. This is not a unified diff. Decode exact update hunks into `edits` without inventing positions, or retain only file activity if decoding is uncertain. Add-file content can supply `after.text` when its bytes are established.

Join `custom_tool_call_output` through `call_id`. A matching `patch_apply_end` with `success: true` establishes application. Fold it with the output into one result, not two. A request alone stays `proposed`. Completed `FileChange.changes` entries are keyed by path. Native `type: add` and `delete` carry full `content`, supplying `after.text` and `before.text` respectively. `type: update` carries `unified_diff` as `patch`. A supplied `move_path` is the destination, with the map key as `oldPath`. Successful completion establishes `applied`. Progress-only updates can contain empty delete placeholders or custom hunks, so they do not establish full contents or unified patches. Fold results at the final contributing observation under the [ordering rule](../spec/format.md#file-format-and-order).

## Commit evidence

For `exec_command`, retain `cmd` and `workdir` from arguments. A linked execution outcome and output `[branch short-id] subject` for an actual `git commit` support a `vcs` action with `parsed_output`, `commitPrefix` and `subject`. Preserve structured `exit_code` only when recorded. Neither a final reply nor a successful unrelated command proves a commit. Parent fields require their own source evidence. PR attachments become `pr_link` with `reported` evidence.

## Usage arithmetic

`token_usage_record.usage` uses `input_tokens` as inclusive `inputTokens` and `output_tokens` as inclusive `outputTokens`. Map supplied `cached_input_tokens`, `cache_write_input_tokens` and `reasoning_output_tokens` to `cacheReadTokens`, `cacheWriteTokens` and `reasoningTokens`. Preserve absent members and recorded zeros. Do not add those subsets again. Keep `total_tokens` in `_meta`, without adding it to either total.

For recorded `token_count.info.total_token_usage`, `input_tokens` and `output_tokens` map directly to session totals. `cached_input_tokens` maps to `cacheReadTokens` when supplied. Repeated totals replace each other. They do not become per-call inferences. `turn_context.model` supplies the requested model. Usage records do not identify the served model. A recorded `response_id` still establishes an inference when the turn model is absent. Omit `model` and declare its loss. Cost is not recorded.

## Missing data

List `model` when the served model is absent, `usage` when call accounting is unavailable, and `copies` when inherited boundaries cannot be resolved. Legacy model-facing shell text does not establish a numeric exit-code field. Compaction summaries use `origin: compaction`, with a gap where history was lost. Opaque reasoning bytes are excluded.

## Capture coverage

| Area | Saved evidence and mapping |
|---|---|
| Messages | Rollout response items retain prompts, replies, reasoning summaries and part authorship where supplied |
| Tool calls | Calls and outputs use `call_id`. Retained completion events can establish execution and edits |
| Approvals | Ordinary rollouts discard structured requests, resolutions and automatic-review events. Import `codex.tool_decision` as approval records by `call_id` or list `approvals` in `missing`. Its `decision` is opaque and needs a version-specific decoder |
| Agent settings and asking | Turn snapshots retain native approval and sandbox policies. See the `asks` mapping below |
| External sandbox | Saved `external-sandbox` supplies `externalSandbox.source: setting` and the native policy. Container or VM kind is not established. Its declared `network_access` does not prove the outer boundary's configuration |
| Triggers | Source distinguishes clients and subagents. Schedule, webhook and channel origins are not documented. `exec` does not establish a scheduled run |
| Hooks | `hook_started` and `hook_completed` are not durable rollout events. Permission hooks report as `Config` in decision telemetry |
| Store changes | The recorder appends and flushes JSONL. Resolve native segments, compression and archived files before conversion |
| Omissions and pruning | Ephemeral sessions do not persist. Tool outputs can be truncated. The rollout is selected history. List `agent_settings` when policy snapshots are unavailable |

In 0.144.3 through 0.163.0 the decision strings are `approved`, `approved_for_session`, `denied`, `abort` and `timed_out`, alongside structured policy amendments. Decode native `approved` as `approved` with `once`, `approved_for_session` as `approved` with `session`, and established persistent policy amendments as `approved` with `always`. Native `denied` and `abort` supply `denied` in these reviewed versions. `timed_out` supplies `cancelled` for an unanswered request. Preserve the decision in `native`. Set `by: user` only when the recorded decision source establishes a person's answer, `policy` for a `Config` decision or established grant reuse, and `classifier` for `AutomatedReviewer`. `Config` alone cannot establish `hook`. A current policy file cannot establish any per-call decision.

For ordinary policies with human review, `never` supplies `asks: never`, while `on-request` and `untrusted` supply `asks: sometimes`. Granular profiles, automatic review and per-call overrides can change whether a person is asked. Omit `asks` when the available snapshot cannot establish it, and supply it again after a native policy change when it remains known. An external sandbox declaration stays separate from the native policy.

## Source versions

These mappings describe rollouts from 0.144.3 through 0.163.0. The range does not establish every field in every release. Publish a native sample for each claimed version, including execution notifications used to establish application.

The [0.163.0 sample](https://github.com/agentsessionrecord/asr/tree/main/samples/codex) pairs a synthetic native rollout with its export and file digests. Tool retention, token members and completed file endpoints are checked against the [rollout policy](https://github.com/openai/codex/blob/ff2346f33f851bd4e90c8e42ae60abcc7e7f293b/codex-rs/rollout/src/policy.rs), [protocol](https://github.com/openai/codex/blob/ff2346f33f851bd4e90c8e42ae60abcc7e7f293b/codex-rs/protocol/src/protocol.rs) and [patch conversion](https://github.com/openai/codex/blob/ff2346f33f851bd4e90c8e42ae60abcc7e7f293b/codex-rs/core/src/apply_patch.rs).

Capture details are checked against the [rollout policy](https://github.com/openai/codex/blob/275a9a89b6/codex-rs/rollout/src/policy.rs), [protocol](https://github.com/openai/codex/blob/275a9a89b6/codex-rs/protocol/src/protocol.rs) and [telemetry](https://github.com/openai/codex/blob/275a9a89b6/codex-rs/otel/src/events/session_telemetry.rs) on October 30, 2026.

## Worked example

This synthetic excerpt records a patch and its successful completion. Derived ASR IDs use physical line and sub-slot. The sample lacks model calls, served model, reasoning and event times, as its `missing` list records.

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
