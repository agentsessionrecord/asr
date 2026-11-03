# Rebase

[rebase.jsonl](rebase.jsonl) records a successful rebase. The source includes
exact rewrite pairs from a repository hook. The pairs are not inferred from
subjects, similar patches or the shell's success message.

A blame reader follows each new commit back to the old commit while checking
candidate sessions. Performing the rebase does not make this session the editor
of the rewritten lines. The commit IDs are illustrative.

[rewrite-history.annotations.jsonl](rewrite-history.annotations.jsonl) supplies
a person's later rewrite of the [coding session's commit](coding-session.md).
Assume both objects exist, the original short ID passes its checks and the edit
survives in the successor. The reader carries the original committed-by history
and edited-by answer to the successor. It identifies the person as the rewriter,
without claiming that the original session performed the rewrite.

The later PR lookup does not erase the rewrite annotation. Both independent
test results remain visible. The corrected title replaces the first even though
its learned time is older, because `supersedes` is applied first. If the PR's
merge commit has one parent, that commit itself is the landed commit to check.
