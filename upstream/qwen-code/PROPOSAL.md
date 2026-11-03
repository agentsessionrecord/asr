# Native Agent Session Record export

Export current and saved Qwen chats in a stable format that other tools can
read.

For [Qwen Code](https://github.com/QwenLM/qwen-code):

```sh
qwen sessions export --format agent-session --session SESSION_ID
```

Adds ASR to the existing `/export` menu alongside JSON and JSONL.
`/export agent-session [directory]` and offline `sessions export` share one
projection. Same-UUID fragments and repeated results fold at completion.

The exporter writes ASR 0.1 from legacy ChatRecord transcripts. It preserves
retained text, reasoning and tool results, declares missing facts and filters
known credentials. Review exports before sharing them.

Managed transaction journals are rejected. Approval decisions, model-call
boundaries, complete settings, accounting, edits, commits and copy detection
remain unavailable. Loaded unsafe integers fail slash export. Offline wide
integers remain exact strings.

The workspace build, 64 focused tests across three files, CLI type check and
focused ESLint pass. Synthetic native fixture exports pass the ASR validator
with zero errors and zero warnings. Tests cover mapping, ordering, corrupt
input, credential filtering and output selection.
