---
title: Code links and blame
description: Find the session that edited a line and the session that committed it.
sidebar:
  order: 5
---

For blame, a reader checks the facts in an Agent Session Record file against the real repository. It gives two separate answers, **edited by** and **committed by**, and they can differ. A session can commit a person's work, and a person can commit an agent's work.

## Line to commit

**ASR-046** A reader deriving blame MUST use the repository's `git blame` result to identify the introducing commit and the path at that commit, and MUST resolve candidate record paths against the session's repositories and verify them against the real repository.

A recorded repository path can name any directory inside the work tree. If a session lists no repository, a reader can use `cwd` once it confirms that `cwd` lies inside the real work tree. Each candidate file path is resolved and normalized against the Git root, and paths outside the work tree are rejected. The `cwd` fallback gives no repository to a `vcs` action and earns no edit or commit credit by itself.

Call the introducing commit C. A reader finds candidate sessions by repository, file path, commit IDs or external session links. A mention in a prompt or reply helps search but is not attribution. The reader's Git options decide which commit `git blame` returns.

In this stream, the `git commit` output gives a short ID and subject, and the `vcs` record keeps just those.

```jsonl
{"type":"session","id":"header","formatVersion":"0.1","agent":{"name":"com.example.agent"},"sessionId":"session-7","producer":{"name":"example-converter","version":"1.0","method":"converter","source":"example-jsonl"},"cwd":"/work/app","repos":[{"path":"/work/app","branch":"fix/empty"}]}
{"type":"message","id":"prompt-1","turnId":"turn-1","role":"user","author":"human","origin":"prompt","content":[{"type":"text","text":"Return an empty list for empty input."}]}
{"type":"inference","id":"model-call-1","turnId":"turn-1","model":{"provider":"example","id":"example-model-1","requested":"default"}}
{"type":"tool_call","id":"edit-call","turnId":"turn-1","inferenceId":"model-call-1","callId":"edit-1","name":"replace_text","kind":"edit","requestedBy":"model","input":{"path":"/work/app/src/parser.py","oldText":"    return text.split(',')\n","newText":"    return text.split(',') if text else []\n"},"locations":[{"path":"/work/app/src/parser.py"}]}
{"type":"tool_result","id":"edit-result","callId":"edit-1","status":"completed","content":[{"type":"text","text":"Replacement applied."}]}
{"type":"file_change","id":"change-1","path":"/work/app/src/parser.py","op":"modify","status":"applied","callId":"edit-1","edits":[{"oldText":"    return text.split(',')\n","newText":"    return text.split(',') if text else []\n"}]}
{"type":"tool_call","id":"commit-call-record","callId":"commit-call","name":"shell","kind":"execute","inputText":"git commit -m 'Handle empty input'"}
{"type":"tool_result","id":"commit-result","callId":"commit-call","status":"completed","exec":{"cwd":"/work/app","exitCode":0,"output":"[fix/empty 8e2f4a6] Handle empty input\n 1 file changed, 1 insertion(+), 1 deletion(-)\n"}}
{"type":"vcs","id":"commit-1","action":"commit","status":"completed","evidence":"parsed_output","callId":"commit-call","repo":"/work/app","commitPrefix":"8e2f4a6","subject":"Handle empty input"}
```

The IDs and paths are made up. A reader runs the checks below against its own repository. It never guesses the rest of a prefix or replaces the recorded command output.

## Rewritten commits

**ASR-047** Readers MUST use recorded `rewrites` pairs from completed actions in candidate streams and annotations to walk backward from C to commits that existed during sessions, checking that both objects exist. They MUST carry verified committed-by history forward and recheck edited-by matches against surviving lines in the successor. For a completed amend without a pair, they MAY use `headBefore` and `commit` when both are recorded and both objects exist. They MUST NOT infer pairs from subjects or patch similarity, or transfer edit authorship to a session merely because it rewrote a commit.

Keep the original and successor commits distinct. A rebase can produce several pairs. A stream action's pair counts when the action passes the status rule in [Committed by](#committed-by). An annotation's pair needs `status: completed`. A pair only yields candidates, because lines may not survive conflict resolution.

An annotation can carry a session's credit forward to the successor even when a person did the rewrite. That does not make the session the rewriter. A session that made the successor earns its own commit credit only through the checks below.

## Committed by

**ASR-048** A reader MUST credit a session with committing a candidate only through its original `vcs` record for `commit`, `amend`, `merge`, `rebase`, `cherry_pick` or `revert`, with `evidence` of `observed` or `parsed_output`, and `status: "completed"`. Only when `vcs.status` is `unknown` MAY a uniquely paired `completed` tool result establish success.

Original means the record is not a copy under the [copy credit rule](sessions.md#copies-and-credit). A successful tool call alone is not a commit record. A `pr_link`, a commit mention, `git log` output, a push or a checkout earns no committed-by credit, and neither does an unknown action or evidence value.

**ASR-049** The candidate MUST equal the recorded full `commit` or a `rewrites[].to`, or pass every abbreviated-ID check below. A reader MUST withhold credit if any recorded check fails.

A `commitPrefix` passes only if all of these hold.

1. The prefix resolves uniquely to the candidate in the repository.
2. The recorded `subject` exactly equals the candidate's subject.
3. The repository shows zero or one parent for `commit`, `amend`, `cherry_pick` or `revert`, or at least two parents for `merge`.
4. Any recorded `parents` equal the actual parent list, and any recorded `parentCount` equals its length.
5. The candidate is reachable from a local branch or tag.

A prefix needs the recorded subject, while parent fields are optional. A `rebase` needs full commit IDs or rewrite pairs, because a prefix alone does not identify the commits it rewrote. For a full commit ID, also compare any recorded subject or parent fields. A branch name alone does not identify a commit.

In the example, say the prefix resolves uniquely to C, the subject matches, C has one parent and C is reachable from a local branch. Then the original, completed `vcs` record supports “committed by `com.example.agent:session-7`.” If the prefix is ambiguous or any check fails, committed-by stays unknown.

## Edited by

C's added lines are the lines added in the diff from C's first parent. For a root commit, every line of the file counts as added. Recorded file states come from `text`, or from available content that matches `objectId` and its hash type.

**ASR-050** Readers MUST derive line attribution only from original, applied `file_change` records and lines the edit added that survive among C's added lines at the resolved path. With both `before` and `after` content, they MUST use only lines added between those states. With `edits`, they MUST use only lines added between `oldText` and `newText`, excluding unchanged context. An `after` match alone MUST NOT credit changes already present before the edit.

A recorded `patch` gives added lines in order. A replacement snippet needs a unique match, and repeated or ambiguous matches attribute nothing. An `after` state alone needs evidence of the state before the edit, such as an observed clean baseline or a confirmed new file. Without it, the reader cannot tell this edit from uncommitted changes already in the worktree. A matching final blob or `baseCommit` is not enough.

For these checks, an applied `move` or `copy` with `oldPath` carries candidate edits from the source path to the destination. The move or copy does not become the author of the carried text.

**ASR-051** Readers MUST select the latest surviving change when its order is established and show earlier matches as alternatives. They MUST credit `actor: "human"` to a person, leave `actor: "external"` untracked, and MUST NOT attribute lines from a file-touch record without matching text evidence.

Within a stream, file order decides which edit is latest, and timestamps do not change it. If the reader cannot order the candidate sessions, it leaves the competing matches unresolved. Without line evidence, a reader can still say a session touched a file.

In the example, compare `change-1` with C's added lines in `src/parser.py`. If the replacement line appears exactly once among them and is unchanged, it supports edited-by credit. From the match, `callId` leads to `edit-call`, `inferenceId` to `model-call-1` and `turnId` to the prompt. This works even when a person made the commit and the session has no `vcs` record.

## Answers

**ASR-052** Readers MUST report edited-by and committed-by results separately and MUST NOT present commit credit as line authorship or a match as proof. For an edited line's model, they MUST use the served model of the inference that produced the causing call when recorded, otherwise its requested model labeled as requested.

For the example, the answer links the edited line to `com.example.agent:session-7#change-1`, the prompt, the causing call and the served model. It links commit credit to `com.example.agent:session-7#commit-1` separately. Another answer might be “edited by this session, committed by a person”, or either half might be unknown.

Show missing prompts, models, calls and related sessions as unresolved. Do not take a model from a nearby reply, and do not infer a human prompt from a message's role.

## Pull requests

**ASR-053** Readers MUST distinguish a session's `pr_open` or `pr_merge` action from a `pr_link` reference. They MUST obtain a pull request's commits from `pr.mergeCommit`, `pr.commits` or annotations. For a merge with multiple parents, they MUST use commits reachable from the other parents but not the first. When `pr.mergeCommit` has one parent, they MUST include that commit itself as the landed commit and apply the edited-by checks to its added lines.

For a two-parent merge, that range is `merge^1..merge^2`. A forge lookup can find a pull request's merge commit, but the session that ran the lookup does not become its author. `pr.commits` can be incomplete. A squash or rebase merge with one parent can hold edits from sessions whose original commits are not its ancestors. Rewrite pairs carry commit history forward, and the surviving text still needs the edit checks. A failed or unknown pull request action does not show that the session completed it.

## Other sources

**ASR-054** Readers MUST treat an `Agent-Session` trailer or Git AI note as a candidate link for the committed-by checks, never as line proof by itself. Writers of Git AI notes from ASR MUST use edited-by results for line attribution.

The [integration guide](../guides/integration.md) covers the commit trailer, and the [Git AI guide](../guides/git-ai.md) covers its session join key and note format.
