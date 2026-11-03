---
title: "Gemini CLI"
description: "Converter notes for Gemini CLI chat recordings."
---

These notes describe `gemini-cli`. Native details without a core field can use `_meta` under `com.google.gemini-cli`.

## Logs and format

Use `producer.source: "gemini-cli-jsonl"` for the journal. `gemini-cli-chat-recording` also names legacy whole-document JSON. Prefer a migrated `.jsonl` to its `.json` sibling. Several recording segments can belong to one session. The saved sample uses `~/.gemini/tmp/<project>/chats/`. Child recordings can live at `chats/<parent session ID>/<child>.jsonl`.

## Session identity

Use metadata `sessionId` verbatim, with no namespace for this format. Neither `projectHash` nor a filename timestamp identifies a session.

## User and settings

Native user identity, reasoning effort, output token limit, temperature and service tier are not documented in these recording mappings. Agent mode, approval policy and sandbox policy are also not documented. Stored `model` identifies model selection, not those settings. Token counts and thought summaries do not establish a reasoning setting.

Leave these settings absent unless a supported source version records them for the call or turn. A separately observed Git identity or configured exporter identity can supply `user` with its own `source`. Do not derive identity from the project path or prompt text.

## Record and call IDs

Messages have `id`. `toolCalls[].id` or GenAI `functionCall.id` and `functionResponse.id` supply `callId`. A result embedded in one uniquely identified call can use that structural join. Derive absent IDs deterministically, without inventing joins between unrelated items.

A token report attached to one model response supports an inference ID derived from its message ID. Give the message and inference distinct IDs. Native `turnId` is not documented. Stored `model` is requested configuration, not the served model.

Fold repeated `pushMessage` observations by message ID. Join chunks by concatenation and keep completed work in native order. `$rewindTo` and `$set.messages` change retained history. They are not human prompts. A snapshot that discarded history needs a gap.

## Subagents and parents

`kind: subagent` with the parent/child path above establishes `parent.kind: subagent`. `kind: main` does not establish that no parent exists. The launching call pointer and copy boundaries are not documented. Shared IDs or similar text do not supply them.

## File-edit evidence

Map `replace` and `write_file` to `kind: edit`, `read_file` to `read` and `run_shell_command` to `execute`. Leave other kinds absent without a documented map.

`toolCalls[].args` holds input. `replace` takes `file_path`, `old_string`, `new_string` and optional `allow_multiple`. Confirmed exact replacements map to `edits`. `write_file` takes `file_path` and full `content`.

The pinned tools can adjust proposed content. Prefer the recorded result over unverified input. `resultDisplay` can retain `filePath`, `fileDiff`, `originalContent`, `newContent` and `isNewFile`. A recorded per-file unified `fileDiff` maps to `patch`. Established full contents map to `before.text` and `after.text`. A failed read's empty fallback does not establish an empty original file.

Native tool `status: success` maps to `completed`, `error` to `failed` and `cancelled` to `cancelled`. Mark a change `applied` only when the result establishes the write. Retain user modifications as metadata. Do not infer model authorship for those modifications. Model-facing `result` and display-only `resultDisplay` serve different purposes.

## Commit evidence

A `run_shell_command` call stores its command in `args.command`. For an actual `git commit`, a linked successful result containing `[branch short-id] subject` supports a parsed-output action with that prefix and subject. Do not invent parent information or infer a commit from a message. A dedicated structured Git-result layout is not documented.

## Usage arithmetic

In `tokens`, `input` already includes `cached`, so `inputTokens = tokens.input`. When `output` exists, `outputTokens = tokens.output + (tokens.thoughts ?? 0)`. Emit `cacheReadTokens` from `cached` and `reasoningTokens` from `thoughts` only when supplied. An absent optional thought count does not discard the recorded output count. Counts lost through corruption remain unknown.

Keep native totals and tool-token counts in `_meta` without adding overlapping totals. Thought descriptions become reasoning summaries. A cost mapping is not documented.

## Missing data

List `copies` when copied history cannot be detected and `model` when the served model is unknown. List unavailable edit, commit or usage mappings. Only `<tool_output_masked>` markers inside `functionResponse.response.output` establish masking. Mark shortened text and unavailable tool output, retaining sibling media and available content. `displayContent` remains separate from model-facing content.

## Capture coverage

| Area | Saved evidence and mapping |
|---|---|
| Messages | Metadata, messages, thought summaries and journal updates. Rewinds can discard reconstructed history |
| Tool calls | Names, arguments, results, status and timestamps survive in the completed-call projection |
| Approvals | Structured `outcome` is omitted from transcripts. `gemini_cli.tool_call` telemetry normalizes it to `accept`, `reject`, `modify` or `auto_accept`, losing scope. A reliable per-call join and decider are not documented here. Ordinary converters emit no approval records and list `approvals` in `missing` |
| Agent settings and asking | Active mode, sandbox and policy rules are not recorded in ordinary transcripts. `asks` is not derivable. List `agent_settings` in `missing` |
| External sandbox | The `SANDBOX` launcher marker exists but is not persisted. Ordinary converters omit `externalSandbox`. A live writer observing an outer boundary can record `source: environment`, leaving kind absent unless established |
| Triggers | Saved `kind: main/subagent` and nesting establish delegation. Schedule, webhook and channel fields are not documented. Headless execution does not identify a trigger |
| Hooks | BeforeTool can block or change input. `gemini_cli.hook_call` is separate telemetry. Ordinary content can retain effects without a structured hook audit |
| Store changes | The JSONL journal appends messages, patches and rewinds. Legacy whole-document JSON is a snapshot |
| Omissions and pruning | Session retention can delete recordings and artifacts. Disk-full handling can stop recording while work continues. Telemetry privacy controls do not redact transcripts |

Native live outcomes include `proceed_once`, `proceed_always`, `proceed_always_and_save`, server/tool variants, `modify_with_editor` and `cancel`. These do not survive as such in ordinary recordings. In the checked telemetry mapper, `proceed_always_and_save` falls through to `reject`. Do not treat that normalized value as a faithful denial or infer `by` or `scope` from it. Extra telemetry needs a documented join and version check before it supplies approval records.

## Source versions

Storage samples describe 0.52.0 resume and recording segments. The pinned [recording types](https://github.com/google-gemini/gemini-cli/blob/a5c49a5c4ab5ebe8119c3b363772ad043bbc4ceb/packages/core/src/services/chatRecordingTypes.ts), [replace tool](https://github.com/google-gemini/gemini-cli/blob/a5c49a5c4ab5ebe8119c3b363772ad043bbc4ceb/packages/core/src/tools/edit.ts) and [write tool](https://github.com/google-gemini/gemini-cli/blob/a5c49a5c4ab5ebe8119c3b363772ad043bbc4ceb/packages/core/src/tools/write-file.ts) establish the fields above. These sources do not establish every field in every release. Publish a safe sample for each supported version.

Capture details are checked against the [recording service](https://github.com/google-gemini/gemini-cli/blob/a609466/packages/core/src/services/chatRecordingService.ts) and [decision mapper](https://github.com/google-gemini/gemini-cli/blob/a609466/packages/core/src/telemetry/tool-call-decision.ts) on October 30, 2026.

## Worked example

This synthetic journal excerpt includes the final recorded file states. The usage lacks an optional thought count. Its output count is still usable. The `missing` list identifies the unknown served model and copy detection.

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
