# Kimi Code native export patch

## Install

Use a separate writable checkout of the upstream project. The supported base is
`9ab1286b8fe4e6bcd116949a27ce5e0ac3389c82`. [manifest.json](manifest.json) pins
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
kimi sessions export --session SESSION_ID --format agent-session --output exports
```

## What it records

The typed wire JSONL supplies text, readable reasoning, assembled calls, final tool results, explicit approval responses and observed plan-mode updates. Streamed pieces fold at completion.

Output uses ASR 0.1 with `producer.method: native`. Known credential fields and
recognized secret text are excluded. Keep exports private and review content
before sharing. Pattern filtering cannot identify every secret.

## Limits

Media, opaque state, instructions, model accounting, file changes and commits are omitted. An approval response alone does not identify a person or policy. This patch targets its pinned Python source, not the 2.x hook adapter.

The [proposal](PROPOSAL.md) describes the source profile and detailed losses.
Valid ASR does not establish complete source capture.

## Tests and status

Run from the ASR repository root with its Node dependencies installed:

```sh
node upstream/kimi-code/check.mjs
node upstream/kimi-code/reproduce.mjs /path/to/upstream-checkout
```

The package check verifies file hashes, patch syntax, synthetic source contracts
and ASR sample validation. The reproduce command also replays the series in a
temporary Git index against the pinned source commits. It preserves the source
checkout. It needs both pinned commits in that checkout and does not build or
run the agent. Upstream build and test evidence is in the proposal.

Live-test status: **partial**.
The evidence below is from a prior revision. A live run of the current code has not been verified.
An isolated source CLI run through the local Responses endpoint exported 7 records with zero validator errors or warnings. The installed entry point was also used for export. The retained evidence contains counts and codes only.

The package's [synthetic export](samples/asr/session.jsonl) has zero validator
errors. Any expected extension or pairing warnings are explained by the proposal
or printed by the package check. Package checks make no model requests.
