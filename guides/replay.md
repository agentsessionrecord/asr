---
title: "Replaying sessions"
description: "Test a change to a prompt, model or setting against recorded work."
---

Recorded Agent Session Record (ASR) sessions can test a change to a system prompt, model or setting against real work. A [step replay](#step-replay) asks one model call again, a [fork](#fork-from-a-point) continues from a chosen point, and a [full re-run](#full-re-runs) starts over from the first prompt.

## What a session supplies

- Prompts, replies, tool calls and tool results, in order.
- System and developer instructions, as messages with `origin: "instructions"` at the positions where they apply.
- The tools offered at each position, from the last `session_info.tools` before it.
- The model and settings each call sent, in `inference.model` and `inference.settings`, and the configured `modelSettings`, mode and native policies in `session_info.agentSettings`.
- The start commit in `repos[].head` and the starting directory in `cwd`.
- File changes, as full file states, patches or replacement text.
- Usage and cost for each model call.

Check `missing` and every `gap` before choosing a session. A session missing `file_changes`, `agent_settings`, `tools`, `model` or `usage` supports fewer comparisons.

## What it leaves out

ASR doesn't record the exact context the model received. After compaction the model saw a summary in place of the earlier history, and after a rewind the abandoned branches stay in the stream in native order, so the records before a call are not that call's input. A gateway between the agent and the model API can capture each request exactly. Use such a capture for exact model inputs and the session to find the call and its effects.

`head` names a commit, so uncommitted changes at the start are not recorded. A tool called again can return something different from the recorded result. Outside services appear only as tool output and known secrets are excluded, so a run that needs a token or a live service has to supply its own.

## Step replay

Step replay asks one model call again. Pick an `inference` record. The records whose `inferenceId` names it, such as a tool call or a reply, are what the call produced. Rebuild the request from the records before the first of them, or before the `inference` record if that comes first, so the call's own answer is never included. Use the tool list in effect at that point and the call's recorded settings.

A model call is written where it completed, so records that completed while it ran can come before that point, and the tool list there may differ from the one offered when the request began. Without a captured request, the rebuilt request and tool list are approximate, and a compaction summary, gap or abandoned branch before the call makes them differ further.

Change one thing, such as the system prompt, the model or a setting, send the request, and compare the next action with the recorded one, for example the tool chosen and its arguments. No tools run, because the recorded results stand in for them, so step replay is cheap enough to test a prompt across many sessions.

## Fork from a point

A fork lets a variant continue from a chosen record, for example a hard bug after several failed attempts. Check out the start commit in a fresh sandbox and apply the session's applied `file_change` records before that point, in file order. Full `after` text or a patch rebuilds a file directly, and replacement `edits` need a unique match in the file.

The rebuilt files are unknown when a change can't be applied, a gap lies before the point, or `missing` lists `file_changes`. Choose an earlier point or skip the session. Commands that write files often leave no `file_change` record, so read the recorded commands before trusting the files.

Give the variant the recorded conversation up to that point and the change under test, then let it continue. The replay tool writes recorded file contents but never runs commands found in the stream. The variant agent runs its own commands inside the sandbox, so a fork costs more than a step replay.

## Full re-runs

A full re-run starts from the first prompt and the start commit, with the recorded instructions, tools, mode and policies except whichever one is under test.

Models are not deterministic, so run each variant several times on the same sessions. Compare test results, cost from per-call usage, the number of turns (model calls or distinct `turnId` values), and each run's diff from the start commit against the recorded diff.

## Record the runs

Record each run as its own session. A run that branched from the recorded history uses `parent.kind: "fork"`, with `parent.record` naming the last record the two share, and a full re-run that reuses the recorded prompt can be a fork at that prompt. Use `continues` when a run stops and picks up again under a new session ID. Record these links only when the replay tool started the run from that session, never from similar text.

Mark [copied history](../spec/sessions.md#copies-and-credit) with `copiedThrough` for a prefix right after the header, or `copiedFrom` on a single record, so each run's cost and edits cover only its own work. Put the variant label and run number in the header's `_meta` under the replay tool's reverse-DNS key. Test results go in `test` [annotations](../spec/annotations.md), and a `title` annotation can name the run.

This run replaces the system prompt and reuses the recorded prompt, so the copied prompt carries `copiedFrom`:

```jsonl
{"type":"session","id":"header","formatVersion":"0.1","agent":{"name":"com.example.agent","version":"1.0"},"sessionId":"replay-7-b-2","producer":{"name":"example-export","version":"1.0","method":"native"},"cwd":"/work/app","repos":[{"path":"/work/app","head":"3f9c2d18a7b64e05c1d2e3f4a5b6c7d8e9f0a1b2"}],"parent":{"session":"com.example.agent:session-7","kind":"fork","record":"prompt-1"},"_meta":{"com.example.replay":{"variant":"short-system-prompt","run":2}}}
{"type":"message","id":"instructions-1","role":"system","origin":"instructions","content":[{"type":"text","text":"Make the smallest change that passes the tests."}]}
{"type":"message","id":"prompt-1","copiedFrom":{"session":"com.example.agent:session-7","record":"prompt-1"},"role":"user","author":"human","origin":"prompt","content":[{"type":"text","text":"Return an empty list for empty input."}]}
```

The replay tool adds the test result and a title in the annotations file:

```jsonl
{"type":"annotation","id":"test-b-2","session":"com.example.agent:replay-7-b-2","kind":"test","at":"2026-10-27T09:00:00Z","source":{"name":"example-replay","version":"1.0"},"data":{"status":"passed","name":"pytest"}}
{"type":"annotation","id":"title-b-2","session":"com.example.agent:replay-7-b-2","kind":"title","at":"2026-10-27T09:00:00Z","source":{"name":"example-replay","version":"1.0"},"data":{"title":"Short system prompt, run 2"}}
```

## Privacy

Replay sends recorded code, prompts and tool output to a model again, possibly from another provider with other data terms. Replay only sessions the requester may read, with the same approval the original data needed. A redacted export replays the redacted text, so its results can differ from the original. Keep run sessions and gateway captures under the same access and retention rules as their source sessions.
