-- Recorded completed actions with full commit IDs only.
-- These are associations. Repository verification is required for blame.
SELECT repo, commit_id, COUNT(DISTINCT session_ref) AS sessions
FROM vcs
WHERE original = true AND status = 'completed'
  AND evidence IN ('observed', 'parsed_output')
  AND action IN ('commit', 'amend', 'merge', 'rebase', 'cherry_pick', 'revert')
  AND commit_id IS NOT NULL
GROUP BY repo, commit_id;
