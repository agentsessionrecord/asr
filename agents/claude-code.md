---
title: "Claude Code"
description: "Converter notes for Claude Code session logs."
---

These notes describe `claude-code`. Native details without a core field can use `_meta` under `com.anthropic.claude-code`.

## Logs and format

Use `producer.source: "claude-code-jsonl"`. Main transcripts live at `~/.claude/projects/<encoded working directory>/<sessionId>.jsonl`. Children use `<sessionId>/subagents/agent-<agentId>.jsonl` with an `agent-<agentId>.meta.json` sidecar. The directory encoding is not identity.

## Session identity

Use `sessionId` for the main transcript and `agentId` for a child. Child records carry the parent's `sessionId`. The described IDs need no namespace.

## User and settings

Some transcripts contain a `session_context` attachment with `context.userEmail`. It can supply `user.email` with `source: _session_context`, without establishing an authenticated account. Otherwise use a separately observed Git or configured exporter identity with its source.

The call's recorded `message.usage.service_tier` supplies `inference.settings.serviceTier`. Linked `api-request` records can supply `params.max_tokens` as `maxOutputTokens` and `params.output_config.effort` as `reasoningEffort`. Temperature is not documented. Do not infer settings from model names or usage counts.

Metadata entry `mode` supplies `agentSettings.mode`. Metadata entry `permission-mode` and prompt `permissionMode` supply `agentSettings.approval` verbatim. Write a `session_info` for the initial values and each recorded change. Repeated identical metadata is not a change. A session sandbox policy is not documented. `dangerouslyDisableSandbox` is a tool-call override, so keep it under `com.anthropic.claude-code` in that call's `_meta`.

In 2.1.305, `api-request-shape.tools` records the offered tool list. Map each recorded `name`, `description` and `input_schema` to `session_info.tools` as `name`, `description` and `inputSchema`, before the associated call. Supply a replacement list when it changes. Record captured system prompt text as `message` with `role: system` and `origin: instructions`, at its recorded position. Tool definitions and instructions follow the same safety rules as other content.

## Record and call IDs

Keep the last snapshot for each repeated `uuid`, at the observation that completed it. Distinct assistant blocks sharing `message.id` belong to one model call. Keep completed items in source order and emit one `inference` at its final contributing observation, taking usage and stop reason from that observation. Link every resulting message and call through `inferenceId`. This avoids counting repeated usage several times.

Use `uuid` for user and harness records. Derive IDs when splitting records. `tool_use.id` and `tool_result.tool_use_id` supply `callId`. `promptId` supplies `turnId`. HTTP `requestId` is separate metadata.

`origin.kind: human` establishes human authorship, including human queued input with `origin: queued`. `isMeta: true` identifies injected harness context. Peer, coordinator and observer messages use `author: agent`, with `from` when `fromSession` identifies the sender. Notifications carrying another session's report also use `agent`. A harness-generated task notice remains `harness`. Unclassified input has no known author.

Model `tool_use` requests use `requestedBy: model`. User `!` shell commands use `requestedBy: user`. `tool_call.input` holds the arguments the tool received, including a recorded `updatedInput` rewrite. Keep a differing recorded model request in `_meta`. An explicit `is_error: true` establishes failure and `is_error: false` establishes completion. When `is_error` is absent, a structured `toolUseResult` object also establishes completion. Otherwise the outcome stays unknown. Retain denial or cancellation markers when available.

## Subagents and parents

Sidecar `toolUseId`, parent result `agentId` and `agentType` establish the launching call, child and role. `forkedFrom {sessionId, messageUuid}` establishes copied records. `fork-context-ref {parentSessionId, parentLastUuid}` names referenced history without a copied prefix. `continuedInSessionId` on `continued-in` identifies a successor. Keep native `parentUuid` tree order and abandoned work.

## File-edit evidence

Map `Edit`, `MultiEdit`, `Write` and `NotebookEdit` to `edit`, `Read` to `read`, `Bash` and `PowerShell` to `execute`, `Glob`, `Grep` and `ToolSearch` to `search`, and `WebFetch` and `WebSearch` to `fetch`. Map `TodoWrite` to `think` and `EnterPlanMode` and `ExitPlanMode` to `switch_mode`. `AskUserQuestion` uses `other`, with the question in the call input and the person's recorded answer in the result. Other names use `other`.

`Edit` input has `file_path`, `old_string` and `new_string`. Map confirmed replacements to `edits`. `MultiEdit` has `file_path` and ordered `edits[]` with those string fields. `Write` has `file_path` and full `content`.

The SDK result schemas describe `Edit` fields `filePath`, `oldString`, `newString`, `originalFile` and `structuredPatch`. `Write` results have `type: create|update`, `filePath`, `content`, `originalFile` and `structuredPatch`. Use these when retained in `toolUseResult` on the result row. Available full contents map to `before.text` and `after.text`. A null `originalFile` alone does not mean an empty file. Structured hunks are not unified patch text. Do not synthesize `patch` from them.

A successful result must establish application. In SDK results, `staged: true` means the file is unchanged, so use `proposed`. Keep `userModified` in metadata. `MultiEdit` result details and the complete `bashEditDiff` payload are not documented here. An `edited_text_file` event identifies an external edit.

## Commit evidence

`gitOperation` on a Bash result is parsed command output. Its full commit payload is not documented here. For a linked `Bash` request with `input.command` invoking `git commit`, a successful result containing `[branch short-id] subject` supports `commitPrefix` and `subject`, with `evidence: parsed_output`. Do not invent parent counts. A command that prints commit history does not establish a commit action. Stored `pr-link` is `pr_link` with `reported` evidence.

## Usage arithmetic

For `message.usage`, when `input_tokens` exists, set `inputTokens = input_tokens + (cache_read_input_tokens ?? 0) + (cache_creation_input_tokens ?? 0)`. Emit `cacheReadTokens` and `cacheWriteTokens` only for supplied fields. `output_tokens` maps directly to inclusive `outputTokens`. Never add reasoning again. Missing optional components do not prevent the total. Counts lost through corruption remain unknown.

`cost-state` supplies session totals, separate from per-call sums. Leave `includesSubagents` absent unless established.

## Missing data

List `exit_codes` because transcript shell results lack numeric exit codes. Report unavailable external tool-output files with `tool_output`, and shortened text with `truncated`. Map `isCompactSummary` after `compact_boundary` to `origin: compaction`, with a gap when history was lost. Declare any unsupported edit, commit, usage or copy mapping.

## Capture coverage

| Area | Saved evidence and mapping |
|---|---|
| Messages | Prompts, replies and injected context. Repeated `uuid` entries use the last snapshot |
| Tool calls | `tool_use.id`, input and linked `tool_result.tool_use_id`. Shell escape requests remain native input |
| Approvals | Result-row `permissionDecision` holds `decision`, `source` and optional `reasonType`. Emit an `approval` record before the result and name it in the result's `approvalId`. `accept` maps to `approved`, `reject` to `denied`. An explicit unanswered abort maps to `cancelled`. See the decider and scope limits below |
| Agent settings and asking | `permissionMode` and mode metadata record changes. `default`, `acceptEdits` and `plan` support `asks: sometimes`. See the limits below for modes that suppress ordinary prompts |
| External sandbox | Detection and cloud launcher markers exist, but their persistence is not documented. Omit `externalSandbox` from ordinary transcript conversion |
| Triggers | `origin.kind: scheduled` maps to `scheduled`, `channel` to `external`. Keep `scheduledTaskId`, `scheduledFireId` and `fireReason` in `_meta`. Peer input keeps agent authorship. Other webhook distinctions are not documented |
| Hooks | `stop_hook_summary`, hook attachments and `permissionDecision.source: hook` retain some effects. PreToolUse can change `updatedInput`. Allow/defer reasons may exist only in debug logs |
| Store changes | JSONL with repeated snapshots. An append-only guarantee for the native transcript is not documented |
| Omissions and pruning | Retention sweeps and disabled persistence can remove history. List `approvals` when decisions or telemetry are unavailable, and `agent_settings` for the absent sandbox policy |

`auto`, `dontAsk` and `bypassPermissions` suppress ordinary prompts, but ask rules and protected actions can still prompt. Use `asks: never` only when recorded effective settings establish no such prompts. Supply `asks` again after a native policy change when it remains known. Otherwise the summary becomes unknown.

Derive a separate approval ID from the result row's `uuid` and a decision sub-slot. Link it through `tool_result.tool_use_id`, and keep `permissionDecision` in `native`. A result timestamp alone does not establish the decision time, so omit `ts` unless that time is recorded separately.

For `by`, `reasonType: mode` maps to `mode`, `source: hook` to `hook`, and other established config decisions to `policy`. Telemetry `classifier_verdict` or an observed `reasonType: classifier` maps to `classifier`. The transcript value is not confirmed for 2.1.305. `user_reject` identifies a person's denial. `user_temporary` and `user_permanent` can describe grants rather than a fresh answer. Set `user` only for an established answer to this request, `policy` for established reuse, or omit `by` when they cannot be distinguished.

`user_temporary` does not distinguish `once` from `session`. An established persistent grant supplies `always`. Correlated `claude_code.safety_event.grant_scope` can supply `once` or `session`. The [monitoring documentation](https://code.claude.com/docs/en/monitoring-usage#tool-decision-event) describes `claude_code.tool_decision` with `tool_use_id`, `decision`, `source` and `classifier_verdict`. Join by call ID within the session without counting transcript and telemetry copies twice.

### Live hooks

`PermissionRequest` reports a request, not the person's choice, and lacks `tool_use_id`. `PermissionDenied` reports automatic-mode denials only. It excludes manual denials, PreToolUse rejection and deny-rule rejection. It can report a denial without a classifier verdict. Record `decision: denied`, but leave `by` unknown unless the event establishes it. List `approvals` in `missing`. A request, mode or completed tool never supplies an answer.

PreToolUse can expose the original arguments while PostToolUse exposes rewritten arguments. PostToolBatch can repeat the original input, so it does not override PostToolUse input. Keep the model's original request in `_meta`. If the call is already written, put differing effective arguments learned at completion on `tool_result.input`. Fold the outcome and final model-facing output at their completion point, leaving intervening callbacks in place.

SessionStart and SessionEnd can supply receipt-time session endpoints. Stop and SubagentStop do not establish session end. Hooks retain lifecycle timing and rewritten input that transcripts can omit. Transcripts can retain model calls, usage, settings, tool definitions and permission decisions that hooks omit. Join the two by established session and call identities, without counting shared observations twice. A recorder sample needs raw hook inputs, registration settings and its content policy to explain what was observed.

## Source versions

Transcript mappings describe 2.1.219 through 2.1.305. Tool inputs also follow the [1.0.100 SDK schemas](https://unpkg.com/@anthropic-ai/claude-code@1.0.100/sdk-tools.d.ts). Result fields above follow the [Agent SDK 0.3.314 schemas](https://unpkg.com/@anthropic-ai/claude-agent-sdk@0.3.314/sdk-tools.d.ts). Those schemas do not establish that every transcript release stores every result field. Publish a native sample for each supported version.

Capture details include observations of 2.1.305 and the [session documentation](https://code.claude.com/docs/en/sessions), checked October 30, 2026. The native transcript layout is internal and can change between versions. Hook coverage describes 2.1.305 and the [hook reference](https://code.claude.com/docs/en/hooks), checked October 31, 2026. The [2.1.305 transcript sample](https://github.com/agentsessionrecord/asr/tree/main/samples/claude-code) includes its edited native file, ASR output and file digests. It does not reproduce hook-only observations.

## Worked example

This synthetic native excerpt shows an exact replacement and a recorded mode decision. IDs, paths and model names are illustrative. The linked result establishes success. Its `missing` list also names incomplete approval and agent-setting evidence.

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
