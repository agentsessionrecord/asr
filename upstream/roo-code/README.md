# Roo Code native export patch

## Install

Use a separate writable checkout of the upstream project. The supported base is
`b867ec9145750d0ae1ff7f02d35406e9bf2a0b16`. [manifest.json](manifest.json) pins
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

```text
Build the patched extension. Open a task and use its export action.
Select Agent Session Record and save the .jsonl file.
```

## What it records

Saved ApiMessage task history supplies text, reasoning, calls, final results and retained condensed or truncated branches in stored order.

Output uses ASR 0.1 with `producer.method: native`. Known credential fields and
recognized secret text are excluded. Keep exports private and review content
before sharing. Pattern filtering cannot identify every secret.

## Limits

Removed compaction history produces gaps. Missing is_error leaves status unknown. Approvals, settings, model calls, usage, file edits, commits and lineage are incomplete. The patch adds no CLI or discovery command.

The [proposal](PROPOSAL.md) describes the source profile and detailed losses.
Valid ASR does not establish complete source capture.

## Tests and status

Run from the ASR repository root with its Node dependencies installed:

```sh
node upstream/roo-code/check.mjs
node upstream/roo-code/reproduce.mjs /path/to/upstream-checkout
```

The package check verifies file hashes, patch syntax, synthetic source contracts
and ASR sample validation. The reproduce command also replays the series in a
temporary Git index against the pinned source commits. It preserves the source
checkout. It needs both pinned commits in that checkout and does not build or
run the agent. Upstream build and test evidence is in the proposal.

Live-test status: **not-live-tested**.
No VS Code executable or configured extension host is available here. Synthetic native fixtures and a focused provider compile were used.

The package's [synthetic export](samples/asr/session.jsonl) has zero validator
errors. Any expected extension or pairing warnings are explained by the proposal
or printed by the package check. Package checks make no model requests.
