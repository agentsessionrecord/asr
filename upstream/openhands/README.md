# OpenHands Canvas ASR export native export patch

## Install

Use a separate writable checkout of the upstream project. The supported base is
`4ce9c4b874c178297d591f9d01a7e21dc50d757a`. [manifest.json](manifest.json) pins
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
Open a conversation. Choose transcript export.
Select Agent Session Record (.jsonl) and export.
```

## What it records

The Canvas 1.34.0 transcript dialog reads complete paginated history. Messages, system text, tools, effective input, result text and explicit rejection observations are retained.

Output uses ASR 0.1 with `producer.method: native`. Known credential fields and
recognized secret text are excluded. Keep exports private and review content
before sharing. Pattern filtering cannot identify every secret.

## Limits

The API supplies timestamp order without an independent recording sequence. Models, usage, complete approvals, settings, media, file edits, commits and relationships remain incomplete. No CLI or live writer is added.

The [proposal](PROPOSAL.md) describes the source profile and detailed losses.
Valid ASR does not establish complete source capture.

## Tests and status

Run from the ASR repository root with its Node dependencies installed:

```sh
node upstream/openhands/check.mjs
node upstream/openhands/reproduce.mjs /path/to/upstream-checkout
```

The package check verifies file hashes, patch syntax, synthetic source contracts
and ASR sample validation. The reproduce command also replays the series in a
temporary Git index against the pinned source commits. It preserves the source
checkout. It needs both pinned commits in that checkout and does not build or
run the agent. Upstream build and test evidence is in the proposal.

Live-test status: **partial**.
The evidence below is from a prior revision. A live run of the current code has not been verified.
OpenHands SDK 1.42.1 scratch conversation through the verified OpenAI-compatible or Anthropic-compatible endpoint. Four native events exported as five ASR records. Native timezone-free timestamps remain metadata. Canvas dialog has focused coverage. Full local and Cloud UI sessions were not exercised.

The package's [synthetic export](samples/asr/session.jsonl) has zero validator
errors. Any expected extension or pairing warnings are explained by the proposal
or printed by the package check. Package checks make no model requests.
