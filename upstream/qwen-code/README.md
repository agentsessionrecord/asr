# Qwen Code native ASR export patch

Export current and saved Qwen chats in a stable format that other tools can
read.

Upstream: https://github.com/QwenLM/qwen-code

The pinned base is `632b06094e338cf368f075d5b719cfcbc10f99a3`. The manifest
records the local feature commit, patch digest and all package file digests.
Apply from a separate clean upstream checkout at that base:

```sh
git am "$ASR_PACKAGE"/patches/*.patch
qwen sessions export --format agent-session --session SESSION_ID
```

Adds `agent-session` to the existing `/export` menu alongside JSON and JSONL.
`/export agent-session [directory]` and offline `sessions export` share one
projection. Same-UUID fragments and repeated results fold at completion.

The source is legacy ChatRecord transcripts. Managed transaction journals are
rejected. Approval decisions, model-call boundaries, complete settings,
accounting, edits, commits and copy detection remain unavailable. Loaded unsafe
integers fail slash export. Offline wide integers remain exact strings. Known
credential filtering does not establish that an export is safe to share.

Run package checks from the ASR repository root:

```sh
node upstream/qwen-code/check.mjs
node upstream/qwen-code/reproduce.mjs /path/to/upstream-checkout
bun upstream/qwen-code/verify-native.mjs /path/to/upstream-checkout
```

Reproduction compares a temporary Git index with the pinned feature tree. It
preserves the source checkout and does not run a model. The native driver loads
the source exporter, validates a synthetic stream and compares the sample. It
does not exercise an installed full CLI and model session.

The workspace build, 64 focused tests across three files, CLI type check and
focused ESLint pass. Native fixture exports pass the reference validator with
zero errors and zero warnings. [verification.json](verification.json) records
the checked source revision and focused results. See [PROPOSAL.md](PROPOSAL.md)
for the scope.

Current live-model status is unverified. Earlier live evidence is partial and
applies to an older revision. No model run was performed for this refresh.

Submission prerequisites: An approved linked feature issue is required. The
upstream diff stays below 1,200 changed lines.
