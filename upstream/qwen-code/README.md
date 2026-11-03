# Qwen Code native export patch

## Install

Use a separate writable checkout of the upstream project. The supported base is
`9ebd2de1713039b8cb5f60c9982e3d4c450e3a8b`. [manifest.json](manifest.json) pins
this base, the ordered patches and their digests. Read [PROPOSAL.md](PROPOSAL.md)
for the upstream repository, runtime requirements and native build instructions.
These patches are local source changes. They are not installed by the ASR CLI.

Set `ASR_PACKAGE` to this package's absolute path. Run in a clean upstream
checkout at the pinned base:

```sh
git am "$ASR_PACKAGE"/patches/*.patch
```

Build and install the patched agent using its own instructions and the focused
checks in the proposal. To remove the feature, use a clean unpatched build.
Existing exported files remain in their output directory.

## Use

Run with the patched agent. Replace example IDs and input paths with a selected
native session. See the proposal for selection and output options.

```sh
qwen sessions export --format agent-session --session SESSION_ID
qwen sessions export --format agent-session --input transcript.jsonl --session SESSION_ID
qwen sessions export --format agent-session --output exports
```

## What it records

Legacy ChatRecord transcripts supply text, arguments, results, IDs and retained branches. Same-UUID fragments fold at completion. Recorded policies, modes, titles and explicit parent links remain available.

Output uses ASR 0.1 with `producer.method: native`. Known credential fields and
recognized secret text are excluded. Keep exports private and review content
before sharing. Pattern filtering cannot identify every secret.

## Limits

Managed transaction journals are refused. Approval decisions, complete settings, accounting, edits, commits and copy detection remain losses. Full input is held in memory. No live writer or automatic registration is added.

The [proposal](PROPOSAL.md) describes the source profile and detailed losses.
Valid ASR does not establish complete source capture.

## Tests and status

Run from the ASR repository root with its Node dependencies installed:

```sh
node upstream/qwen-code/check.mjs
node upstream/qwen-code/reproduce.mjs /path/to/upstream-checkout
```

The package check verifies file hashes, patch syntax, synthetic source contracts
and ASR sample validation. The reproduce command also replays the series in a
temporary Git index against the pinned source commits. It preserves the source
checkout. It needs both pinned commits in that checkout and does not build or
run the agent. Upstream build and test evidence is in the proposal.

Live-test status: **partial**.
The evidence below is from a prior revision. A live run of the current code has not been verified.
Qwen Code 0.26.5 recorded isolated synthetic message and read-tool sessions through the OpenAI-compatible or Anthropic-compatible endpoint. The focused patched export command produced ASR with zero validation errors or warnings. Full pinned CLI installation and workspace release checks were not run.

The package's [synthetic export](samples/asr/session.jsonl) has zero validator
errors. Any expected extension or pairing warnings are explained by the proposal
or printed by the package check. Package checks make no model requests.
