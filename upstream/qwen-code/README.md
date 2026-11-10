# Agent Session Record export for Qwen Code

This patch adds ASR to the existing `/export` menu in [Qwen Code](https://github.com/QwenLM/qwen-code), next to JSON and JSONL, for current and saved chats. `/export agent-session [directory]` and the offline `sessions export` command share one mapping. The pinned base is `632b06094e338cf368f075d5b719cfcbc10f99a3`. [Apply the patch](../README.md#apply-a-patch) in a clean checkout at that base.

```sh
qwen sessions export --format agent-session --session SESSION_ID
```

The source is legacy ChatRecord transcripts, and managed transaction journals are rejected. Fragments with the same UUID and repeated results are folded together when they complete. Approval decisions, model-call boundaries, complete settings, accounting, edits, commits and copy detection are unavailable. Unsafe integers in a loaded session stop the slash command, while the offline command keeps wide integers as exact strings. Known credentials are filtered out. See the [proposal](PROPOSAL.md) for the scope.

## Checks

```sh
node upstream/qwen-code/check.mjs
node upstream/qwen-code/reproduce.mjs /path/to/upstream-checkout
bun upstream/qwen-code/verify-native.mjs /path/to/upstream-checkout
```

See [package checks](../README.md#check-a-package) for the first two. `verify-native.mjs` loads the exporter from the patched source, validates a synthetic export and compares it with the sample, without running the installed CLI or a model.

The workspace build, 64 focused tests across three files, the CLI type check and focused ESLint pass. Native fixture exports validate with no errors or warnings. [verification.json](verification.json) records the source revision and results. An earlier live run was partial and covered an older revision. No live model run covers this one.

Upstream requires an approved linked feature issue. The upstream diff stays under 1,200 changed lines.
