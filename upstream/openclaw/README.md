# OpenClaw native export patch

## Install

Use a separate writable checkout of the upstream project. The supported base is
`15e4d849d5f9a3559132454aeff90fe54781dee9`. [manifest.json](manifest.json) pins
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
openclaw sessions export --format agent-session --agent main --all --output ./asr
openclaw sessions export --format agent-session --session NATIVE_SESSION_ID
```

## What it records

Read-only SQLite session windows supply messages, tools, explicit call IDs, inclusive usage, offered tools, reasoning settings and approvals. Verified receipts can establish applied file changes.

Output uses ASR 0.1 with `producer.method: native`. Known credential fields and
recognized secret text are excluded. Keep exports private and review content
before sharing. Pattern filtering cannot identify every secret.

## Limits

Missing prompts, complete policy history, served models, call settings, attachments and shell edits are not reconstructed. PostgreSQL, cold archives and legacy JSONL import are outside this patch.

The [proposal](PROPOSAL.md) describes the source profile and detailed losses.
Valid ASR does not establish complete source capture.

## Tests and status

Run from the ASR repository root with its Node dependencies installed:

```sh
node upstream/openclaw/check.mjs
node upstream/openclaw/reproduce.mjs /path/to/upstream-checkout
```

The package check verifies file hashes, patch syntax, synthetic source contracts
and ASR sample validation. The reproduce command also replays the series in a
temporary Git index against the pinned source commits. It preserves the source
checkout. It needs both pinned commits in that checkout and does not build or
run the agent. Upstream build and test evidence is in the proposal.

Live-test status: **partial**.
The evidence below is from a prior revision. A live run of the current code has not been verified.
Fresh scratch session against a local OpenAI-compatible endpoint exported from native SQLite with the current source owner. Nine records validate with zero errors and zero warnings. The full CLI exporter was not rebuilt for this run.

The package's [synthetic export](samples/asr/session.jsonl) has zero validator
errors. Any expected extension or pairing warnings are explained by the proposal
or printed by the package check. Package checks make no model requests.
