# Subagent

[parent.jsonl](parent.jsonl) records a review request and the returned result.
[child.jsonl](child.jsonl) names the parent and its launching call.
Each file can be read without the other.

The child's first message is copied history. `parent.copiedThrough` names its
local ID, so the copy receives no credit as the child's own work. The new model
call and reply belong to the child. Its requested model stays labeled as requested.
