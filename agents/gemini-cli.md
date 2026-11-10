---
title: "Gemini CLI"
description: "Converter notes for Gemini CLI chat recordings."
---

Gemini CLI chat recordings convert to Agent Session Record (ASR) with the [shared mappings](index.md#shared-mappings) and the rules below. Unmapped native fields can go in `_meta` under `com.google.gemini-cli`.

## Logs and format

Use `producer.source: "gemini-cli-jsonl"` for the JSONL journal and `gemini-cli-chat-recording` for legacy whole-document JSON. Prefer a migrated `.jsonl` to its `.json` sibling. One session can have several recording segments. The saved sample uses `~/.gemini/tmp/<project>/chats/`, and child recordings can be at `chats/<parent session ID>/<child>.jsonl`.

## Session identity

Use metadata `sessionId` verbatim, with no `namespace`. Neither `projectHash` nor a timestamp in the file name identifies a session.

## User and settings

The recordings document no user identity, reasoning effort, output token limit, temperature, service tier, agent mode, approval policy or sandbox policy. Stored `model` is the model selection only, and thought summaries do not establish a reasoning setting. Do not derive identity from the project path or prompt text.

## Record and call IDs

Messages have `id`. `toolCalls[].id`, or GenAI `functionCall.id` and `functionResponse.id`, supply `callId`. A result embedded in one uniquely identified call can join to it by structure. Derive absent IDs deterministically, without joining unrelated items.

A token report attached to one model response supports an inference with an ID derived from, but distinct from, the message ID. No native `turnId` is documented. Stored `model` is the requested model, not the served one.

Fold repeated `pushMessage` observations by message ID, concatenating chunks. `$rewindTo` and `$set.messages` change retained history and are not human prompts. A snapshot that discarded history needs a `gap`.

## Subagents and parents

`kind: subagent` with the parent and child path above establishes `parent.kind: subagent`, but `kind: main` does not prove there is no parent. The launching call and copy boundaries are not documented.

## Tool kinds and file edits

Map `replace` and `write_file` to `kind: edit`, `read_file` to `read` and `run_shell_command` to `execute`. Leave other kinds absent.

Input is in `toolCalls[].args`. `replace` takes `file_path`, `old_string`, `new_string` and optional `allow_multiple`, and confirmed exact replacements map to `edits`. `write_file` takes `file_path` and full `content`.

The pinned tools can adjust proposed content, so prefer the recorded result over the input. `resultDisplay` can keep `filePath`, `fileDiff`, `originalContent`, `newContent` and `isNewFile`. A recorded per-file unified `fileDiff` maps to `patch`, and established full contents to `before.text` and `after.text`. The empty fallback after a failed read does not mean the original file was empty.

Tool `status: success` maps to `completed`, `error` to `failed` and `cancelled` to `cancelled`. Keep user modifications as metadata, without crediting them to the model. The model sees `result`, while `resultDisplay` is for display only.

## Commits

`run_shell_command` stores its command in `args.command`. No structured Git result layout is documented.

## Token usage and cost

In `tokens`, `input` already includes `cached`, so `inputTokens = tokens.input`. When `output` exists, `outputTokens = tokens.output + (tokens.thoughts ?? 0)`. Emit `cacheReadTokens` from `cached` and `reasoningTokens` from `thoughts` only when supplied. Keep native totals and tool-token counts in `_meta` without adding overlapping totals. Thought descriptions become reasoning summaries. No cost mapping is documented.

## Missing data

List `copies` when copied history cannot be detected, `model` when the served model is unknown, and `agent_settings` because mode, sandbox and policy rules are not recorded. Only `<tool_output_masked>` markers inside `functionResponse.response.output` establish masking. Mark shortened text and unavailable tool output, keeping sibling media and the content that is available. `displayContent` stays separate from model-facing content.

## Approvals and agent settings

Transcripts omit the structured approval `outcome`. Live outcomes include `proceed_once`, `proceed_always`, `proceed_always_and_save`, server and tool variants, `modify_with_editor` and `cancel`. `gemini_cli.tool_call` telemetry normalizes them to `accept`, `reject`, `modify` or `auto_accept` and loses scope, and in the checked mapper `proceed_always_and_save` falls through to `reject`. Do not treat that value as a real denial or infer `by` or `scope` from it. No reliable per-call join or decider is documented, so ordinary converters write no approval records and list `approvals` in `missing`. Other telemetry needs a documented join and version check before it can supply approvals.

Active mode, sandbox and policy rules are not recorded, so `asks` cannot be derived. The `SANDBOX` launcher marker is not saved either, so ordinary converters omit `externalSandbox`. A live writer that observes an outer boundary can record it with `source: environment`, leaving the kind absent unless established.

## Triggers, hooks and storage

| Area | What the recordings keep |
|---|---|
| Triggers | Saved `kind: main/subagent` and nesting establish delegation. Schedule, webhook and channel fields are not documented. Headless execution does not identify a trigger |
| Hooks | BeforeTool can block or change input. `gemini_cli.hook_call` is separate telemetry. Content can keep hook effects without a structured hook audit |
| Store changes | The JSONL journal appends messages, patches and rewinds, and rewinds can discard reconstructed history. Legacy whole-document JSON is a snapshot |
| Pruning | Session retention can delete recordings and artifacts. A full disk can stop recording while work continues. Telemetry privacy controls do not redact transcripts |

## Source versions

Storage samples describe 0.52.0 resume and recording segments. The pinned [recording types](https://github.com/google-gemini/gemini-cli/blob/a5c49a5c4ab5ebe8119c3b363772ad043bbc4ceb/packages/core/src/services/chatRecordingTypes.ts), [replace tool](https://github.com/google-gemini/gemini-cli/blob/a5c49a5c4ab5ebe8119c3b363772ad043bbc4ceb/packages/core/src/tools/edit.ts) and [write tool](https://github.com/google-gemini/gemini-cli/blob/a5c49a5c4ab5ebe8119c3b363772ad043bbc4ceb/packages/core/src/tools/write-file.ts) establish the fields above. Approval, trigger, hook and storage details follow the [recording service](https://github.com/google-gemini/gemini-cli/blob/a609466/packages/core/src/services/chatRecordingService.ts) and [decision mapper](https://github.com/google-gemini/gemini-cli/blob/a609466/packages/core/src/telemetry/tool-call-decision.ts), checked October 30, 2026.

## Worked example

This synthetic journal includes the final recorded file states. Its usage has no thought count, but the output count still applies. `missing` names the unknown served model and copy detection.

```jsonl native
{"sessionId":"example-gemini","startTime":"2026-10-26T14:00:00Z","kind":"main"}
{"id":"prompt-1","timestamp":"2026-10-26T14:00:00Z","type":"user","content":[{"text":"Make an empty limit mean zero."}]}
{"id":"reply-1","timestamp":"2026-10-26T14:00:00Z","type":"gemini","content":[],"model":"example-model","tokens":{"input":10,"output":5},"toolCalls":[{"id":"edit-1","name":"replace","args":{"file_path":"/work/parser.py","old_string":"limit = int(value)\n","new_string":"limit = int(value or \"0\")\n"},"status":"success","timestamp":"2026-10-26T14:00:00Z","result":[{"functionResponse":{"id":"edit-1","name":"replace","response":{"output":"Replacement applied."}}}],"resultDisplay":{"filePath":"/work/parser.py","originalContent":"limit = int(value)\n","newContent":"limit = int(value or \"0\")\n","isNewFile":false}}]}
```

The ASR stream is:

```jsonl
{"type":"session","id":"header","formatVersion":"0.1","agent":{"name":"gemini-cli"},"sessionId":"example-gemini","producer":{"name":"example-converter","version":"1.0","method":"converter","source":"gemini-cli-jsonl"},"missing":["model","copies","approvals","agent_settings"],"startedAt":"2026-10-26T14:00:00Z"}
{"type":"message","id":"prompt-1","ts":"2026-10-26T14:00:00Z","role":"user","content":[{"type":"text","text":"Make an empty limit mean zero."}]}
{"type":"inference","id":"reply-1:inference","ts":"2026-10-26T14:00:00Z","model":{"requested":"example-model"},"usage":{"inputTokens":10,"outputTokens":5}}
{"type":"tool_call","id":"reply-1:call","callId":"edit-1","name":"replace","kind":"edit","input":{"file_path":"/work/parser.py","old_string":"limit = int(value)\n","new_string":"limit = int(value or \"0\")\n"},"inferenceId":"reply-1:inference"}
{"type":"tool_result","id":"reply-1:result","callId":"edit-1","ts":"2026-10-26T14:00:00Z","status":"completed","content":[{"type":"text","text":"Replacement applied."}]}
{"type":"file_change","id":"reply-1:change","callId":"edit-1","path":"/work/parser.py","op":"modify","status":"applied","before":{"text":"limit = int(value)\n"},"after":{"text":"limit = int(value or \"0\")\n"}}
```
