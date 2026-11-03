# Reader interpretation cases

These cases describe expected reader answers. They are not validator checks.
Use repository objects with the stated relationships and preserve each source
record while evaluating the cases.

| Case | Evidence | Expected answer |
|---|---|---|
| Short commit output | The [coding session](../examples/coding-session.md), a unique prefix, exact subject, zero or one repository parent and a containing local branch or tag | Commit credit resolves without recorded parent fields. |
| Prefix mismatch | The same record with an ambiguous prefix, wrong subject, incompatible parent count or no containing local branch or tag | No commit credit. Recorded parent IDs or counts also have to match when supplied. |
| Outcome precedence | A commit action with `status: failed` and a completed paired tool result | No commit credit. With `unknown`, the completed result can establish success. With `completed`, that VCS status decides even if the paired result failed. |
| Dirty worktree | The [before and after example](../examples/dirty-worktree.md) | Only the limit line receives session edit credit. The owner's existing dirty change does not. |
| Replacement context | The same example expressed as replacements containing the unchanged owner line | Diff `oldText` against `newText`. The owner line receives no session edit credit. |
| File states by hash | Both snapshot object IDs resolve to the dirty-worktree example's file states | The answer matches the text snapshots. An unresolved before-state does not justify credit from the after-state alone. |
| Root commit | A confirmed add-file edit whose content survives in a root commit | All root-commit lines are candidates, but only matching lines added by the edit receive credit. |
| Move or copy | An applied move or copy follows the recorded replacement | Carry the source-path candidate to the destination. The move or copy does not author unchanged text. |
| Rewritten history | The [later rewrite annotations](../examples/rebase.md), with both objects present and the edit surviving | Carry original verified commit history and surviving edit credit forward. The annotation does not make the original session the rewriter. |
| Rewrite failure | A failed rewrite, or a pair whose repository object is absent | No verified successor attribution through that pair. |
| Single-parent PR merge | The later PR annotation names a single-parent landed commit | Evaluate that commit itself, including edits retained by a squash. |
| Multiple sessions | Independent sessions have competing surviving matches but no established order | Keep competing matches unresolved. Timestamps do not choose a winner. |
| Additive facts | Two VCS and two test annotations on the same target | Keep all four unless explicitly superseded. A later PR lookup does not erase a rewrite. |
| Corrected current value | A title correction has `supersedes` and an older `at` | Exclude the corrected title first, then select the latest remaining current value. |
| Outcome merge link | An `outcome` annotation supplies `pr.mergeCommit` | Use it for PR checks, without granting edit or commit credit from the annotation alone. |
| User label and authorship | The [identity and settings session](../examples/identity-and-settings.md) has `user` and a harness notice with `role: user` | Group by the recorded user without treating the notice as that person's prompt or giving them commit credit. |
| Partial agent settings | The same session changes only `mode`, then only `approval` and `sandbox` | After the first update, retain `on-request` and `read-only`. After the second, retain mode `execute`. Omitted fields and an empty `agentSettings` object erase nothing. |
| Unstated model settings | The first turn's two inferences record the same settings, while the next turn records only reasoning effort | Display both calls' recorded settings. Leave the next call's temperature, output limit and tier unknown. Do not fill defaults or carry settings across turns. |
| Settings position | The [approval and policy session](../examples/approvals-and-policy.md) changes policy after its first call | Use the recorded settings before each record in file order. Do not apply `policy-change` to the first call. |
| Settings merge | `policy-change` supplies `asks` and only `modelSettings.reasoningEffort` | Keep the native sandbox and configured temperature. An empty `modelSettings` changes nothing. A supplied `externalSandbox` replaces the whole boundary, so an empty object clears it. |
| Stale asking summary | The [policy-change fixture](fixtures/asks-policy-change/stream.jsonl) changes native `approval` without supplying `asks` | Treat the earlier `asks` as unknown for the call. Do the same when `mode` or `sandbox` changes. A supplied `asks` establishes the summary again without interpreting the native policy. |
| Configured model | The same example has configured model settings and an inference without `settings` | The call's settings stay unknown. The configured values do not establish what it sent. |
| Several answerers | The scheduled prompt's person differs from the approval's person and the next message's person | Preserve each identity without replacing the session user or changing message authorship. |
| Reused approval | The first decision comes from a remembered grant and the second from a fresh answer | Preserve source order. Report the first as `policy` with `session` scope and the second as `user` with `once` scope. Neither establishes tool success. |
| Unknown approvals | A completed or denied result has no recorded approval decision, or the session lists `approvals` missing | Do not reconstruct a decision from the result or assume that the displayed decisions are complete. |
| Decision before disconnect | The [disconnect fixture](fixtures/approval-disconnect/stream.jsonl) ends after an approval and has no result | Keep the decision and its time. The call's outcome remains unknown. |
| Decisions around settings | The [settings-change fixture](fixtures/approval-settings-change/stream.jsonl) has two decisions for one call around an update | Keep both IDs, times and subjects. Read the policy before each decision, including the changed policy for the second. |
| Grant with no call | The [grant fixture](fixtures/approval-no-call/stream.jsonl) has a subject and no `callId` | Display the grant without inventing a call or result. |
| Copied approvals | Approval records fall within `copiedThrough` or carry `copiedFrom` | Credit the decisions to the source session. Do not count them as decisions in the copying session. |
| Late loss | The [live-loss fixture](fixtures/live-losses/stream.jsonl) starts with missing usage and loses approval coverage after a completed call | The known losses become `usage` and `approvals`. The empty update removes neither. Keep the earlier captured decision usable and show the gap. |
| Offered tools | The [tools fixture](fixtures/tools-valid/stream.jsonl) supplies definitions, then an empty list | Use the definitions from their position until the empty list replaces them. An update omitting `tools` retains the list. Before any list is recorded, it is unknown. |
| Arrival and authorship | The same session has a human-written scheduled prompt and an external message | Report origin separately from the recorded author. A headless client alone supplies neither scheduled nor external origin. |
| Redacted version | The [redacted copy](../examples/approvals-redacted.jsonl) has the same session identity and an exact-byte source digest | Keep file versions distinct. Verify the source link when bytes are available, without treating it as proof of completeness. |

## Completion and missing facts

| Case | Evidence | Expected answer |
|---|---|---|
| Folded observations | [Live recording](../examples/live-recording.jsonl) has a tool outcome, an intervening notice and final output | Keep the notice before the result. Use the final observation's time for the result and retain the first observation only as metadata. |
| Snapshot decision | The same example stores the decision on the result | Place the approval immediately before that result without inferring a decision time or its order against unrelated events. |
| Effective arguments | The call records `echo requested`, while the result records `echo executed` | The effective input is `echo executed`. Preserve both records and pair only through the unique call ID. Null and empty input are supplied values. |
| Live lifecycle | The recorder observes explicit session start and end events | Use their receipt times for the session endpoints. A turn stop, an idle period or EOF alone leaves the end unknown. |
| Cleared settings | [Partial evidence](../examples/partial-evidence.jsonl) clears effort and service tier but omits temperature | Effort and tier become unknown. Temperature remains zero as a configured fact. The next inference's own settings remain unknown. |
| Cleared objects | The [clear fixture](fixtures/settings-clear/stream.jsonl) supplies null for the outer boundary and configured model object | Both become unknown. An empty settings object alone changes nothing. |
| Partial offered tools | The partial example lists `read` and declares `tools` missing | `read` is recorded as offered. No conclusion follows about an unlisted tool. |
| Unknown model | The same example identifies a call without its model | Keep the inference, its identity and usage. Show the model as unknown. Do not borrow a model from the copied inference. |
| Copied revisions | Two output revisions link to `copied-call` outside a copied prefix | Count the inference once and exclude its copied usage from this session. The new call contributes 12 input and 5 output tokens. |
| Large numbers | The [large-value fixture](fixtures/large-native-values/stream.jsonl) uses `9007199254740993` as a string | Keep every digit. Retaining numeric values from other files also preserves their source spelling without rounding. |
