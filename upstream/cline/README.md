# Cline native export patch

## Install

Use a separate writable checkout of the upstream project. The supported base is
`46996c9992d91e57c268091c971cfda52b0da399`. [manifest.json](manifest.json) pins
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
cline history export SESSION_ID --format agent-session --output ./session.jsonl
```

## What it records

Native session fields, retained message order, exact text, readable reasoning, tool requests and model-facing results. Repeated results fold at their final stored position.

Output uses ASR 0.1 with `producer.method: native`. Known credential fields and
recognized secret text are excluded. Keep exports private and review content
before sharing. Pattern filtering cannot identify every secret.

## Limits

Approvals, settings, inference boundaries, usage, file edits, commits and lineage remain missing. Compaction can remove history. Unsafe parsed numbers stop export. No live writer or discovery registration is added.

The [proposal](PROPOSAL.md) describes the source profile and detailed losses.
Valid ASR does not establish complete source capture.

## Tests and status

Run from the ASR repository root with its Node dependencies installed:

```sh
node upstream/cline/check.mjs
node upstream/cline/reproduce.mjs /path/to/upstream-checkout
```

The package check verifies file hashes, patch syntax, synthetic source contracts
and ASR sample validation. The reproduce command also replays the series in a
temporary Git index against the pinned source commits. It preserves the source
checkout. It needs both pinned commits in that checkout and does not build or
run the agent. Upstream build and test evidence is in the proposal.

Live-test status: **partial**.
The evidence below is from a prior revision. A live run of the current code has not been verified.
Source CLI 3.0.74 completed a scratch turn through a compatible endpoint. Its patched history command exported 3 records with zero validation errors or warnings.

The package's [synthetic export](samples/asr/session.jsonl) has zero validator
errors. Any expected extension or pairing warnings are explained by the proposal
or printed by the package check. Package checks make no model requests.
