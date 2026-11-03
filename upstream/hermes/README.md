# Hermes native export patch

## Install

Use a separate writable checkout of the upstream project. The supported base is
`c7c7e0fa92f40c8f526e4a52c0966c128245ffd3`. [manifest.json](manifest.json) pins
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
hermes sessions export --format agent-session --session SESSION_ID
hermes sessions export --format agent-session --output exports --since 2026-11-01T00:00:00Z
```

## What it records

A read-only native SQLite snapshot supplies retained text, tool requests and
model-facing results. Result status remains unknown. Native insertion order and
exact retained content govern the export. Explicit branch and delegation markers
can establish parent relationships. Shared message IDs can identify copies from
a direct parent.

Output uses ASR 0.1 with `producer.method: native`. Known credential fields and
recognized secret text are excluded. Keep exports private and review content
before sharing. Pattern filtering cannot identify every secret.

## Limits

Approval history, settings, tools, usage, inference boundaries, exit codes, file changes and commits are incomplete. Removed history cannot be restored. No live sidecar or discovery registration is added.

The [proposal](PROPOSAL.md) describes the source profile and detailed losses.
Valid ASR does not establish complete source capture.

## Tests and status

Run from the ASR repository root with its Node dependencies installed:

```sh
node upstream/hermes/check.mjs
node upstream/hermes/reproduce.mjs /path/to/upstream-checkout
```

The package check verifies file hashes, patch syntax, synthetic source contracts
and ASR sample validation. The reproduce command also replays the series in a
temporary Git index against the pinned source commits. It preserves the source
checkout. It needs both pinned commits in that checkout and does not build or
run the agent. Upstream build and test evidence is in the proposal.

Live-test status: **partial**.
The evidence below is from a prior revision. A live run of the current code has not been verified.
An isolated real agent turn used the OpenAI-compatible or Anthropic-compatible endpoint. The real CLI exported persisted history. ASR validation passed with zero errors and warnings.

The package's [synthetic export](samples/asr/session.jsonl) has zero validator
errors. Any expected extension or pairing warnings are explained by the proposal
or printed by the package check. Package checks make no model requests.
