# ForgeCode native export patch

## Install

Use a separate writable checkout of the upstream project. The supported base is
`a22b49288856d5b3f3ca57e8532683d54a662c8c`. [manifest.json](manifest.json) pins
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
forge conversation dump ID --format agent-session > session.jsonl
```

## What it records

Retained context, conversation identity, start time, text, reasoning summaries, raw tool arguments, native call IDs and results.

Output uses ASR 0.1 with `producer.method: native`. The projection excludes opaque provider state. It does not provide a general
secret-redaction service. Keep exports private and review content before sharing.

## Limits

Earlier context and intermediate events can be missing. Models, usage, approvals, settings, relationships and per-message times are absent. No session end or original interleaving is inferred.

The [proposal](PROPOSAL.md) describes the source profile and detailed losses.
Valid ASR does not establish complete source capture.

## Tests and status

Run from the ASR repository root with its Node dependencies installed:

```sh
node upstream/forgecode/check.mjs
node upstream/forgecode/reproduce.mjs /path/to/upstream-checkout
```

The package check verifies file hashes, patch syntax, synthetic source contracts
and ASR sample validation. The reproduce command also replays the series in a
temporary Git index against the pinned source commits. It preserves the source
checkout. It needs both pinned commits in that checkout and does not build or
run the agent. Upstream build and test evidence is in the proposal.

Current project verification and fixture results are in [refresh.json](refresh.json).
No current live inference test is claimed. Historical live evidence does not
certify this refreshed source.
