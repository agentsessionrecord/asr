# Annotations

[annotations.annotations.jsonl](annotations.annotations.jsonl) adds facts learned
after the [person's commit example](person-commits.md). It includes a title,
summary, test result, outcome and pull request association.

The final title corrects the earlier title through `supersedes`. Its later `at`
makes it the preferred title. The other kinds remain separate. The recorded
commit and pull request facts help find candidates, but they grant no blame
credit by themselves.
