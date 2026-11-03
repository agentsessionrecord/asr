# Deep Agents Code ASR export native export patch

## Install

Use a separate writable checkout of the upstream project. The supported base is
`e9f0d8855cff6d7e79d87afc15c2defc62214a71`. [manifest.json](manifest.json) pins
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
dcode threads export --format agent-session --session THREAD_ID
dcode threads export --format agent-session --output ./exports
```

## What it records

Root-namespace SQLite message writes in native replay order. Message revisions, effective tool arguments, explicit tool outcomes and work removed from later context remain available.

Output uses ASR 0.1 with `producer.method: native`. Known credential fields and
recognized secret text are excluded. Keep exports private and review content
before sharing. Pattern filtering cannot identify every secret.

## Limits

Offloaded history and nested checkpoint namespaces are not recovered. Usage, models, timestamps, settings, approvals, file edits, commits and lineage are incomplete. Pickle fallback is disabled.

The [proposal](PROPOSAL.md) describes the source profile and detailed losses.
Valid ASR does not establish complete source capture.

## Tests and status

Run from the ASR repository root with its Node dependencies installed:

```sh
node upstream/deepagents/check.mjs
node upstream/deepagents/reproduce.mjs /path/to/upstream-checkout
```

The package check verifies file hashes, patch syntax, synthetic source contracts
and ASR sample validation. The reproduce command also replays the series in a
temporary Git index against the pinned source commits. It preserves the source
checkout. It needs both pinned commits in that checkout and does not build or
run the agent. Upstream build and test evidence is in the proposal.

Live-test status: **partial**.
The evidence below is from a prior revision. A live run of the current code has not been verified.
Deep Agents Code 0.2.2 model factory and SDK 0.7.32 graph with native SQLite checkpoint persistence through the verified OpenAI-compatible or Anthropic-compatible endpoint. CLI export wrote three valid ASR records. Full headless Code server and interactive TUI were not exercised.

The package's [synthetic export](samples/asr/session.jsonl) has zero validator
errors. Any expected extension or pairing warnings are explained by the proposal
or printed by the package check. Package checks make no model requests.
