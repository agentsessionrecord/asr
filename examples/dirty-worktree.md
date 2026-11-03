# A dirty worktree

[dirty-worktree.jsonl](dirty-worktree.jsonl) records an agent replacing the limit
line after a person has changed the owner. The first parent's file is:

```python
limit = int(value)
owner = "team"
```

The introducing commit contains the recorded after-state. Both lines differ
from the first parent, but only the limit line differs between the recorded
before and after states. The session receives edited-by credit for the limit
line only. Its matching final snapshot gives no credit for the person's owner
change. With only the after-state and no evidence of the pre-edit state, the
reader cannot distinguish those edits and leaves the line attribution unknown.

Replacing the snapshots with `edits` containing both lines produces the same
answer. The unchanged owner line is context in the replacement, not a line
added by that edit. Git-blob IDs resolving to the same before and after contents
produce the same result. A content hash alone does not supply unavailable text.
