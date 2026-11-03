# Missing data

[missing-data.jsonl](missing-data.jsonl) keeps a compaction summary and the next
prompt. The header lists known losses. The summary is shortened, and a gap marks
history that the source discarded.

The summary remains searchable. It does not establish a file edit or a commit,
and its `user` role does not make it a person's prompt. The later prompt has
separate authorship from the source.
