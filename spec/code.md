---
title: Code links and blame
description: Find the session that edited a line and the session that committed it.
sidebar:
  order: 5
---

ASR records the facts used for blame. A reader checks them against the real repository and reports two answers separately, **edited by** and **committed by**. A session can commit a person's work, and a person can commit an agent's work.

## Line to commit

**ASR-046** A reader deriving blame MUST use the repository's `git blame` result to identify the introducing commit and the path at that commit, and MUST resolve candidate record paths against the session's repositories and verify them against the real repository.

A recorded repository path can identify a directory inside the selected repository's work tree. When a session lists no repository, a reader can treat `cwd` as a candidate location. It verifies that the location lies inside the selected repository's real work tree before using it. The reader resolves and normalizes each candidate file path against the selected Git root and rejects paths outside that work tree. This fallback does not imply a repository for a `vcs` action or establish edit or commit credit on its own.

Call the introducing commit C. A reader first finds candidate sessions by repository, file path, commit IDs or external session links. A mention in a prompt or reply is searchable context, not an attribution result. The reader's Git options determine which commit `git blame` selects.

The following stream records a replacement and a commit. The command prints the new commit's short ID and subject. The converter keeps those facts without inventing parent information.

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

The example's IDs and repository data are illustrative. The checks below use the reader's actual repository. A reader does not expand the prefix by guessing the remaining digits or replace the recorded command output.

## Rewritten commits

**ASR-047** Readers MUST use recorded `rewrites` pairs from completed actions in candidate streams and annotations to walk backward from C to commits that existed during sessions, checking that both objects exist. They MUST carry verified committed-by history forward and recheck edited-by matches against surviving lines in the successor. For a completed amend without a pair, they MAY use `headBefore` and `commit` when both are recorded and both objects exist. They MUST NOT infer pairs from subjects or patch similarity, or transfer edit authorship to a session merely because it rewrote a commit.

Keep the original and resulting commits distinct. A rebase can produce several pairs. A stream action follows the status rule below. An annotation needs `status: completed` to establish a completed rewrite. Walking a usable pair finds candidates for the following checks, without assuming every old line survived conflict resolution. An annotation can connect an original session's credit to a successor even when a person performed the rewrite. It does not make that session the performer of the rewrite. A session that produced the successor earns separate commit credit only through the checks below.

## Committed by

**ASR-048** A reader MUST credit a session with committing a candidate only through its original `vcs` record for `commit`, `amend`, `merge`, `rebase`, `cherry_pick` or `revert`, with `evidence` of `observed` or `parsed_output`, and `status: "completed"`. Only when `vcs.status` is `unknown` MAY a uniquely paired `completed` tool result establish success.

Original means the record passes the [copy credit rule](sessions.md#copies-and-credit). A successful tool call alone is not a commit record. A `pr_link`, a commit mention, `git log` output, a push or a checkout does not establish committed-by credit. An unknown action or evidence value supplies no such credit.

**ASR-049** The candidate MUST equal the recorded full `commit` or a `rewrites[].to`, or pass every abbreviated-ID check below. A reader MUST withhold credit if any recorded check fails.

For `commitPrefix`, all of these checks are needed.

1. The prefix resolves uniquely to the candidate in the repository.
2. The recorded `subject` exactly equals the candidate's subject.
3. The repository shows zero or one parent for `commit`, `amend`, `cherry_pick` or `revert`, or at least two parents for `merge`.
4. Any recorded `parents` equal the actual parent list, and any recorded `parentCount` equals its length.
5. The candidate is reachable from a local branch or tag.

The subject is required for prefix resolution. Parent fields are optional. A `rebase` needs full commit IDs or rewrite pairs because a prefix alone does not identify its rewritten commits. `vcs.status` decides success even when a paired tool result differs. For a full commit ID, compare any recorded subject or parent information as well. A branch name alone does not identify a commit.

For the example, suppose the reader resolves the prefix uniquely to C, verifies the subject and single parent, and finds C reachable from a local branch. The original successful `vcs` record then supports “committed by `com.example.agent:session-7`.” If the prefix is ambiguous or a check fails, that answer stays unknown.

## Edited by

C's added lines are all its file's lines for a root commit, otherwise the lines added in the diff from C's first parent. Resolve recorded file states from `text` or available content matching `objectId` and its hash type.

**ASR-050** Readers MUST derive line attribution only from original, applied `file_change` records and lines the edit added that survive among C's added lines at the resolved path. With both `before` and `after` content, they MUST use only lines added between those states. With `edits`, they MUST use only lines added between `oldText` and `newText`, excluding unchanged context. An `after` match alone MUST NOT credit changes already present before the edit.

A recorded `patch` supplies added lines in order. Replacement snippets need a unique match. Repeated or ambiguous alignments do not attribute lines. An after-state alone needs evidence of the pre-edit state, such as an observed clean baseline or a confirmed new file, to distinguish this edit from dirty worktree changes. A matching final blob or `baseCommit` alone cannot do that.

An applied `move` or `copy` with `oldPath` carries candidate edits at the source path onto the destination for these checks. Carried text does not become newly authored by the move or copy.

**ASR-051** Readers MUST select the latest surviving change when its order is established and show earlier matches as alternatives. They MUST credit `actor: "human"` to a person, leave `actor: "external"` untracked, and MUST NOT attribute lines from a file-touch record without matching text evidence.

File order orders edits within a stream. If the reader cannot establish an order between candidate sessions, it keeps the competing matches unresolved. Timestamps do not reorder a stream. A reader can still say a session touched a file when line evidence is missing.

In the example, compare `change-1` with C's added lines in `src/parser.py`. If the replacement line occurs uniquely among them and survives unchanged, it supports edited-by credit. The match leads through `callId` to `edit-call` and through `inferenceId` to `model-call-1`. The recorded `turnId` links that call to the prompt. The same edit can be attributed when a person makes the commit and the session has no `vcs` record.

## Answers

**ASR-052** Readers MUST report edited-by and committed-by results separately and MUST NOT present commit credit as line authorship or a match as proof. For an edited line's model, they MUST use the served model of the inference that produced the causing call when recorded, otherwise its requested model labeled as requested.

An answer for the example links the edited line to `com.example.agent:session-7#change-1`, the prompt, the causing call and the served model. It separately links commit credit to `com.example.agent:session-7#commit-1`. Another result might say “edited by this session, committed by a person” or leave either level unknown.

Show missing prompts, models, calls and related sessions as unresolved. Do not borrow a model from a nearby reply or infer a human prompt from a message's role. A match is evidence about recorded work, not proof of who caused every byte.

## Pull requests

**ASR-053** Readers MUST distinguish a session's `pr_open` or `pr_merge` action from a `pr_link` reference. They MUST obtain a pull request's commits from `pr.mergeCommit`, `pr.commits` or annotations. For a merge with multiple parents, they MUST use commits reachable from the other parents but not the first. When `pr.mergeCommit` has one parent, they MUST include that commit itself as the landed commit and apply the edited-by checks to its added lines.

A two-parent merge uses `merge^1..merge^2`. A forge lookup can associate a pull request with a merge commit without making the querying session its author. `pr.commits` can be incomplete. A single-parent squash or rebase merge can retain edits from sessions whose original commits are not its ancestors. Recorded rewrite pairs carry commit history forward, and surviving text still needs the edit checks. Failed or unknown pull request actions do not establish that a session completed the action.

## Other sources

**ASR-054** Readers MUST treat an `Agent-Session` trailer or Git AI note as a candidate link for the committed-by checks, never as line proof by itself. Writers of Git AI notes from ASR MUST use edited-by results for line attribution.

The [integration guide](../guides/integration.md) covers the commit trailer. The [Git AI guide](../guides/git-ai.md) describes its session join key and note format. These links help find streams while the repository and recorded edit evidence determine the answers.
