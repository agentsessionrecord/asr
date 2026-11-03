# A person commits an agent's edits

[person-commits.jsonl](person-commits.jsonl) records an agent making an edit.
A person commits the change after the session. That later commit is outside
this stream, so it has no `vcs` record.

A reader can still match `edits[].newText` uniquely against the commit's added
lines. It reports the agent session as the editor and the person as the committer
when separate evidence identifies that person. Otherwise the committer stays
unknown. The [annotations example](annotations.md) records a later outcome.
