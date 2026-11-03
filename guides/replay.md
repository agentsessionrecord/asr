---
title: "Replaying sessions"
description: "Test a change to a prompt, model or setting against recorded work."
---

A recorded session shows what an agent was asked, what it was told and what it did. Those records can test a change to a system prompt, model or setting against real work. This guide describes three levels of replay. This guide adds no requirements.

## What a session supplies

- Prompts, replies, tool calls and tool results, in order.
- System and developer instructions as messages with `origin: "instructions"`, at the positions where they apply.
- The recorded offered tools at each position, from the last `session_info.tools` before it. A `tools` loss means this list can be partial.
- The model and the settings each call sent, from `inference.model` and `inference.settings`. Configured `modelSettings`, the mode and the native policies come from `session_info.agentSettings`.
- The start commit in `repos[].head` and the starting directory in `cwd`.
- File changes, as full file states, patches or replacement text.
- Usage and cost for each model call.

Check `missing` and every `gap` before choosing a session. A session that lists `file_changes`, `agent_settings`, `tools`, `model` or `usage` supports fewer comparisons.

## What it leaves out

ASR does not record the exact context the model received. After compaction, the model saw a summary in place of the history before it. After a rewind, abandoned branches stay in the stream in native order. In both cases the records before a call are not that call's input.

- **Uncommitted changes at the start.** `head` names a commit, not the state of a dirty worktree.
- **Tool behavior.** A recorded result shows what a tool returned once. A new run calls the tool again and can get a different answer.
- **The network and secrets.** Responses from outside services appear only as tool output, and producers exclude known secrets. A run that needs a token or a live service needs its own.

A gateway between the agent and the model API can capture each request exactly. Take exact model inputs from such a capture, and use the session to find the call and its effects. Keep the capture under the same access rules as the session.

## Step replay

Step replay asks one model call again. Pick an `inference` record. Records whose `inferenceId` names it show what the call produced, such as a tool call or a reply. Rebuild the request from the records before the call's first output. That point is the first record whose `inferenceId` names the call, or the `inference` record if it comes first. Never include the call's own answer. Use the tool list in effect at that point and the call's recorded settings.

A model call is written where it completed, so records that completed while it ran can come before that point. The tool list there may differ from the one offered when the request began. The rebuilt request and tool list are approximate unless the source captured the exact request.

Change one thing, such as the system prompt, the model or a setting. Send the request and compare the next action with the recorded one, such as the tool chosen and its arguments.

No tools run, because the recorded results stand in for them. This makes step replay cheap enough to test a prompt across many sessions. Its limit is the rebuilt context. A compaction summary, gap or abandoned branch before the call makes it differ from what the model saw. A gateway capture removes that doubt.

## Fork from a point

A fork lets a variant continue from a chosen record. Check out the start commit in a fresh sandbox. Apply the session's applied `file_change` records before that point, in file order. Full `after` text or a patch rebuilds a file directly. Replacement `edits` need a unique match in the file.

The rebuilt files are unknown when a change cannot be applied, a gap lies before the point, or `missing` lists `file_changes`. Choose a point before the problem or skip the session. Commands that write files often leave no `file_change` record, so read the recorded commands before trusting the files.

Give the variant the recorded conversation up to that point and the change under test, then let it continue. The replay tool writes recorded file contents but never runs commands found in the stream. The variant agent chooses its own commands inside the sandbox.

A fork tests a variant in the same situation, such as a hard bug after failed attempts. Tools run, so it costs more than a step replay.

## Full re-runs

A full re-run starts from the first prompt and the start commit. Give each variant the recorded instructions, tools, mode and policies unless one of them is the change under test.

Models are not deterministic, so one run per variant shows noise as much as difference. Run each variant several times on the same sessions. Compare test results, cost, the number of turns and the final diff. Take cost from per-call usage, and count turns as model calls or distinct `turnId` values. Compare each run's diff from the start commit with the recorded diff.

## Record the runs

Record each run as its own session. A run that branched from the recorded history uses `parent.kind: "fork"`, with `parent.record` naming the last record the two share. A full re-run that reuses the recorded prompt can be a fork at that prompt. Use `continues` when a run stops and picks up again under a new session ID. Record these links only when the replay tool started the run from that session, never from similar text.

Mark copied history with `copiedThrough` for a prefix right after the header, or `copiedFrom` on a single record. Copies receive no credit for cost or edits, so each run's totals cover only its own work.

Put each run's variant label and run number in the header's `_meta` under the replay tool's reverse-DNS key. Test results learned after a run go in `test` annotations, and a `title` annotation can give the run a readable name.

This run replaces the system prompt and reuses the recorded prompt, so the copied prompt carries `copiedFrom`.

```jsonl
{"type":"session","id":"header","formatVersion":"0.1","agent":{"name":"com.example.agent","version":"1.0"},"sessionId":"replay-7-b-2","producer":{"name":"example-export","version":"1.0","method":"native"},"cwd":"/work/app","repos":[{"path":"/work/app","head":"3f9c2d18a7b64e05c1d2e3f4a5b6c7d8e9f0a1b2"}],"parent":{"session":"com.example.agent:session-7","kind":"fork","record":"prompt-1"},"_meta":{"com.example.replay":{"variant":"short-system-prompt","run":2}}}
{"type":"message","id":"instructions-1","role":"system","origin":"instructions","content":[{"type":"text","text":"Make the smallest change that passes the tests."}]}
{"type":"message","id":"prompt-1","copiedFrom":{"session":"com.example.agent:session-7","record":"prompt-1"},"role":"user","author":"human","origin":"prompt","content":[{"type":"text","text":"Return an empty list for empty input."}]}
```

The replay tool adds the test result and a readable title in the annotations file.

```jsonl
{"type":"annotation","id":"test-b-2","session":"com.example.agent:replay-7-b-2","kind":"test","at":"2026-10-27T09:00:00Z","source":{"name":"example-replay","version":"1.0"},"data":{"status":"passed","name":"pytest"}}
{"type":"annotation","id":"title-b-2","session":"com.example.agent:replay-7-b-2","kind":"title","at":"2026-10-27T09:00:00Z","source":{"name":"example-replay","version":"1.0"},"data":{"title":"Short system prompt, run 2"}}
```

## Privacy

Replay sends recorded code, prompts and tool output to a model again. That model can belong to another provider with other data terms. Replay only sessions the requester may read, and get the same approval the original data needed. A redacted export replays the redacted text, so its results can differ from the original session. Keep run sessions and gateway captures under the same access and retention rules as their source sessions.

See [Sessions](../spec/sessions.md), [Annotations](../spec/annotations.md) and [Missing data](../spec/missing-data.md).
