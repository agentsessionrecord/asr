---
title: "Claude Code"
description: "Converter notes for Claude Code session logs."
---

Claude Code's JSONL transcripts convert to Agent Session Record (ASR) with the [shared mappings](index.md#shared-mappings) and the rules below. Unmapped native fields can go in `_meta` under `com.anthropic.claude-code`.

## Logs and format

Use `producer.source: "claude-code-jsonl"`. Main transcripts are at `~/.claude/projects/<encoded working directory>/<sessionId>.jsonl`. Subagents write `<sessionId>/subagents/agent-<agentId>.jsonl` with an `agent-<agentId>.meta.json` sidecar. The encoded directory name is not an identifier. The transcript layout is internal and can change between versions.

## Session identity

Use `sessionId` for the main transcript and `agentId` for a subagent, whose records also carry the parent's `sessionId`. No `namespace` is needed.

## User and settings

A `session_context` attachment's `context.userEmail` can supply `user.email` with `source: _session_context`. It does not prove an authenticated account.

`message.usage.service_tier` supplies `inference.settings.serviceTier`. A linked `api-request` record's `params.max_tokens` and `params.output_config.effort` supply `maxOutputTokens` and `reasoningEffort`. Temperature is not documented.

Metadata `mode` supplies `agentSettings.mode`, and metadata `permission-mode` or prompt `permissionMode` supplies `agentSettings.approval`. Repeated identical metadata is not a change. No session sandbox policy is documented. `dangerouslyDisableSandbox` overrides one tool call, so it goes in that call's `_meta`.

In 2.1.305, `api-request-shape.tools` lists the offered tools. Map each `name`, `description` and `input_schema` to `session_info.tools` as `name`, `description` and `inputSchema` before the associated call, with a new list when it changes. Captured system prompt text becomes a `message` with `role: system` and `origin: instructions` at its recorded position.

## Record and call IDs

Keep the last snapshot of each repeated `uuid`, at the observation that completed it. Assistant blocks that share `message.id` are one model call. Emit one `inference` at its final contributing observation, with that observation's usage and stop reason, and link the resulting messages and calls through `inferenceId`.

User and harness records use `uuid`. `tool_use.id` and `tool_result.tool_use_id` supply `callId`, and `promptId` supplies `turnId`. The HTTP `requestId` is separate metadata.

`origin.kind: human` establishes human authorship, including queued input with `origin: queued`. `isMeta: true` marks injected harness context. Peer, coordinator and observer messages, and notifications carrying another session's report, use `author: agent`, with `from` when `fromSession` names the sender. Harness task notices stay `harness`, and other input has no known author.

Model `tool_use` requests use `requestedBy: model`, and user `!` shell commands use `requestedBy: user`. `tool_call.input` holds the arguments the tool received, including a recorded `updatedInput` rewrite, with a differing model request in `_meta`. Shell escape requests stay native input. An explicit `is_error: true` establishes failure and `is_error: false` establishes completion. When `is_error` is absent, a structured `toolUseResult` object also establishes completion. Otherwise the outcome stays unknown. Keep any denial or cancellation markers.

## Subagents and parents

The sidecar's `toolUseId` and the parent result's `agentId` and `agentType` give the launching call, the child and its role. `forkedFrom {sessionId, messageUuid}` marks copied records, while `fork-context-ref {parentSessionId, parentLastUuid}` refers to parent history without copying it. `continuedInSessionId` on a `continued-in` entry names the successor session.

## Tool kinds and file edits

| `kind` | Native tools |
|---|---|
| `edit` | `Edit`, `MultiEdit`, `Write`, `NotebookEdit` |
| `read` | `Read` |
| `execute` | `Bash`, `PowerShell` |
| `search` | `Glob`, `Grep`, `ToolSearch` |
| `fetch` | `WebFetch`, `WebSearch` |
| `think` | `TodoWrite` |
| `switch_mode` | `EnterPlanMode`, `ExitPlanMode` |
| `other` | `AskUserQuestion` and any other tool |

`AskUserQuestion` keeps the question in the call input and the person's answer in the result.

`Edit` input has `file_path`, `old_string` and `new_string`, and `MultiEdit` has `file_path` and an ordered `edits[]` with the same strings. Confirmed replacements map to `edits`. `Write` input has `file_path` and the full `content`.

The SDK result schemas describe `toolUseResult` when the result row keeps it. `Edit` results have `filePath`, `oldString`, `newString`, `originalFile` and `structuredPatch`. `Write` results have `type: create|update`, `filePath`, `content`, `originalFile` and `structuredPatch`. Full contents map to `before.text` and `after.text`, but a null `originalFile` alone does not mean an empty file. `structuredPatch` hunks are not unified patch text, so never build `patch` from them.

`staged: true` means the file is unchanged, so use `proposed`. Keep `userModified` in metadata. `MultiEdit` result details and the full `bashEditDiff` payload have no documented mapping. An `edited_text_file` event marks an external edit.

## Commits

Commit commands are in a `Bash` call's `input.command`. `gitOperation` on a Bash result is parsed command output, and its full commit payload has no documented mapping. A stored `pr-link` becomes `pr_link` with `reported` evidence.

## Token usage and cost

When `message.usage` has `input_tokens`, set `inputTokens = input_tokens + (cache_read_input_tokens ?? 0) + (cache_creation_input_tokens ?? 0)`. Emit `cacheReadTokens` and `cacheWriteTokens` only for supplied fields. `output_tokens` maps directly to `outputTokens`, which already includes reasoning.

`cost-state` supplies session totals, kept separate from per-call sums. Leave `includesSubagents` absent unless established.

## Missing data

Transcript shell results have no numeric exit codes, so list `exit_codes`. Use `tool_output` for unavailable external tool-output files and `truncated` for shortened text. `isCompactSummary` after `compact_boundary` maps to `origin: compaction`, with a `gap` when history was lost. List `agent_settings` because no sandbox policy is recorded, and `approvals` when decisions or telemetry are unavailable.

## Approvals and agent settings

The result row's `permissionDecision` holds `decision`, `source` and an optional `reasonType`. Write an `approval` before the result, with an ID derived from the row's `uuid` and a decision sub-slot, link it through `tool_result.tool_use_id` and name it in the result's `approvalId`. Keep `permissionDecision` in `native`. A result timestamp alone does not establish the decision time, so omit `ts` unless that time is recorded separately.

`accept` maps to `approved`, `reject` to `denied` and an explicit unanswered abort to `cancelled`. For `by`, `reasonType: mode` maps to `mode`, `source: hook` to `hook` and other established config decisions to `policy`. A telemetry `classifier_verdict` or an observed `reasonType: classifier` maps to `classifier`, though the transcript value is not confirmed for 2.1.305. `user_reject` is a person's denial. `user_temporary` and `user_permanent` can describe an existing grant, so use `user` only for an established answer to this request and `policy` for established reuse. Otherwise omit `by`.

`user_temporary` does not distinguish `once` from `session`, but a correlated `claude_code.safety_event.grant_scope` can supply either. An established persistent grant is `always`. The [monitoring documentation](https://code.claude.com/docs/en/monitoring-usage#tool-decision-event) describes `claude_code.tool_decision` with `tool_use_id`, `decision`, `source` and `classifier_verdict`. Join it by call ID within the session, counting a decision found in both sources once.

`default`, `acceptEdits` and `plan` support `asks: sometimes`. `auto`, `dontAsk` and `bypassPermissions` suppress ordinary prompts, but ask rules and protected actions can still prompt, so use `asks: never` only when recorded effective settings rule those out.

External sandbox detection and cloud launcher markers exist, but they are not documented as saved, so omit `externalSandbox` for ordinary transcripts.

## Triggers, hooks and storage

| Area | What the transcripts keep |
|---|---|
| Triggers | `origin.kind: scheduled` maps to `scheduled` and `channel` to `external`, with `scheduledTaskId`, `scheduledFireId` and `fireReason` in `_meta`. Peer input keeps agent authorship. Other webhook distinctions are not documented |
| Hooks | `stop_hook_summary`, hook attachments and `permissionDecision.source: hook` keep some effects. PreToolUse can change `updatedInput`. Allow and defer reasons may exist only in debug logs |
| Store changes | JSONL with repeated snapshots, not documented as append-only |
| Pruning | Retention sweeps and disabled persistence can remove history |

## Recording from hooks

`PermissionRequest` reports a request without the person's choice or a `tool_use_id`. `PermissionDenied` reports only automatic-mode denials, not manual, PreToolUse or deny-rule rejections, and can lack a classifier verdict. Record its denial with `by` unknown unless the event establishes it, and list `approvals` in `missing`.

PreToolUse shows the original arguments and PostToolUse the rewritten ones. PostToolBatch can repeat the original input, but it does not override PostToolUse. Keep the model's original request in `_meta`, and if the call is already written, put differing effective arguments on `tool_result.input`. Fold the outcome and final model-facing output in at completion, leaving callbacks in between where they are.

SessionStart and SessionEnd can supply session start and end times as received, but Stop and SubagentStop do not end a session. Hooks keep lifecycle timing and rewritten input that transcripts can omit, and transcripts keep model calls, usage, settings, tool definitions and permission decisions that hooks omit. Join the two by established session and call IDs, counting shared observations once. A recorder sample should include the raw hook inputs, registration settings and content policy.

## Source versions

Transcript mappings cover 2.1.219 through 2.1.305. Tool inputs also follow the [1.0.100 SDK schemas](https://unpkg.com/@anthropic-ai/claude-code@1.0.100/sdk-tools.d.ts) and result fields the [Agent SDK 0.3.314 schemas](https://unpkg.com/@anthropic-ai/claude-agent-sdk@0.3.314/sdk-tools.d.ts), which do not show that every release stores every result field. Approval, trigger and storage details come from 2.1.305 and the [session documentation](https://code.claude.com/docs/en/sessions), checked October 30, 2026. Hook details come from 2.1.305 and the [hook reference](https://code.claude.com/docs/en/hooks), checked October 31, 2026. The [2.1.305 transcript sample](https://github.com/agentsessionrecord/asr/tree/main/samples/claude-code) has the edited native file, its ASR output and file digests, but no hook-only observations.

## Worked example

This synthetic transcript has one exact replacement and an approval decided by permission mode. The linked result establishes success, and `missing` also names the incomplete approval and agent-setting evidence.

```jsonl native
{"type":"user","uuid":"prompt-1","sessionId":"example-claude","origin":{"kind":"human"},"message":{"role":"user","content":"Make an empty limit mean zero."}}
{"type":"assistant","uuid":"assistant-1","sessionId":"example-claude","message":{"id":"response-1","role":"assistant","model":"example-model","content":[{"type":"tool_use","id":"edit-1","name":"Edit","input":{"file_path":"/work/parser.py","old_string":"limit = int(value)\n","new_string":"limit = int(value or \"0\")\n"}}],"usage":{"input_tokens":10,"output_tokens":5}}}
{"type":"user","uuid":"result-1","sessionId":"example-claude","permissionDecision":{"decision":"accept","source":"config","reasonType":"mode"},"message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"edit-1","is_error":false,"content":"Replacement applied."}]}}
```

The ASR stream is:

```jsonl
{"type":"session","id":"header","formatVersion":"0.1","agent":{"name":"claude-code"},"sessionId":"example-claude","producer":{"name":"example-converter","version":"1.0","method":"converter","source":"claude-code-jsonl"},"missing":["exit_codes","timestamps","approvals","agent_settings"]}
{"type":"message","id":"prompt-1","role":"user","author":"human","origin":"prompt","content":[{"type":"text","text":"Make an empty limit mean zero."}]}
{"type":"inference","id":"response-1","model":{"id":"example-model"},"usage":{"inputTokens":10,"outputTokens":5}}
{"type":"tool_call","id":"assistant-1","inferenceId":"response-1","callId":"edit-1","name":"Edit","kind":"edit","requestedBy":"model","input":{"file_path":"/work/parser.py","old_string":"limit = int(value)\n","new_string":"limit = int(value or \"0\")\n"}}
{"type":"approval","id":"result-1:approval:1","callId":"edit-1","decision":"approved","by":"mode","native":{"decision":"accept","source":"config","reasonType":"mode"}}
{"type":"tool_result","id":"result-1","callId":"edit-1","status":"completed","approvalId":"result-1:approval:1","content":[{"type":"text","text":"Replacement applied."}]}
{"type":"file_change","id":"result-1:change","callId":"edit-1","path":"/work/parser.py","op":"modify","status":"applied","edits":[{"oldText":"limit = int(value)\n","newText":"limit = int(value or \"0\")\n"}]}
```
