# Coding session

[coding-session.jsonl](coding-session.jsonl) contains the complete session from
the [quick tour](https://agentsessionrecord.org/get-started/quick-tour).
A prompt leads to a model call, a file edit, tests, a commit and a final reply.

The edit keeps the replacement strings. Each tool result pairs with one call.
The commit keeps the printed short ID, subject and recorded parent count.
A reader checks that evidence against the repository before giving commit credit.
Line attribution needs a separate match against the surviving edit.
