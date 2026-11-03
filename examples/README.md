# Examples

These examples use fictional agents, models and repositories. Each session is
one JSON Lines file with a header. Annotations live in their own file.

| Example | What it shows |
|---|---|
| [Minimal session](minimal.md) | A prompt and a reply with only the available facts. |
| [Coding session](coding-session.md) | Model calls, an edit, tests and a commit. |
| [User identity and settings](identity-and-settings.md) | Account identity, per-turn model settings and partial agent-policy updates. |
| [Approvals, policy and collection](approvals-and-policy.md) | Approval records, per-message identity, scheduled work, policy changes, a redacted copy and its collection receipt. |
| [Subagent](subagent/README.md) | Parent and child streams with copied context. |
| [A person commits](person-commits.md) | An agent edit that survives in a person's commit. |
| [Rebase](rebase.md) | Exact commit rewrite pairs and later rewrite annotations. |
| [Dirty worktree](dirty-worktree.md) | Only lines added by the recorded edit receive credit. |
| [Missing data](missing-data.md) | Known losses, a shortened summary and a gap. |
| [Annotations](annotations.md) | Later facts and a corrected title. |

Validate every example from the repository root:

```sh
pnpm --dir tools/validator run examples
```

All examples pass without errors. See the [validator](../tools/validator/README.md)
for individual files and [conformance fixtures](../conformance/README.md) for
inputs that exercise errors and warnings.

## Live recording and partial evidence

[Live recording](live-recording.jsonl) shows a folded tool result after an
intervening callback, a decision stored on the result, effective arguments learned
at completion, and explicit session lifecycle receipt times.

[Partial evidence](partial-evidence.jsonl) keeps a partial tool list, clears
configured settings, links two native revisions to one copied inference, and
records an identified call whose model is unknown. Its native call ID is a
string larger than JavaScript's exact integer range.
