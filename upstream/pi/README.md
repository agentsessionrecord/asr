# Pi native export patch

## Install

Use a separate writable checkout of the upstream project. The supported base is
`a14cdf90f0a76532f3e20bc3c01872837cef24ba`. [manifest.json](manifest.json) pins
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
pi-session-export --session native-session.jsonl --format agent-session --output session.asr.jsonl
```

## What it records

The native v3 session tree is exported in file order, including abandoned branches. It keeps text, reasoning, tools, final results, summaries, injected messages, identified inferences and inclusive usage.

Output uses ASR 0.1 with `producer.method: native`. Known credential fields and
recognized secret text are excluded. Keep exports private and review content
before sharing. Pattern filtering cannot identify every secret.

## Limits

Media, opaque state, approvals, file changes, commits and child lineage are not reconstructed. Failed local settlements without provider identity do not create model calls. Unsupported or corrupt input fails before output.

The [proposal](PROPOSAL.md) describes the source profile and detailed losses.
Valid ASR does not establish complete source capture.

## Tests and status

Run from the ASR repository root with its Node dependencies installed:

```sh
node upstream/pi/check.mjs
node upstream/pi/reproduce.mjs /path/to/upstream-checkout
```

The package check verifies file hashes, patch syntax, synthetic source contracts
and ASR sample validation. The reproduce command also replays the series in a
temporary Git index against the pinned source commits. It preserves the source
checkout. It needs both pinned commits in that checkout and does not build or
run the agent. Upstream build and test evidence is in the proposal.

Live-test status: **partial**.
The evidence below is from a prior revision. A live run of the current code has not been verified.
An isolated source CLI run against a local OpenAI-compatible endpoint exported 9 records, including 2 inference records, a tool call and a result. Validation reported zero errors or warnings. The provider key was read from private provider settings. The generated model catalog was hydrated locally and is not part of this patch.

The package's [synthetic export](samples/asr/session.jsonl) has zero validator
errors. Any expected extension or pairing warnings are explained by the proposal
or printed by the package check. Package checks make no model requests.
