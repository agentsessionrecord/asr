# Grok Build native export patch

## Install

Use a separate writable checkout of the upstream project. The supported base is
`2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8`. [manifest.json](manifest.json) pins
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

This is reference code. Upstream does not accept outside patches.
The ACP transcript in `updates.jsonl` remains separate from this telemetry sidecar.

Run with the patched agent. Replace example IDs and input paths with a selected
native session. See the proposal for selection and output options.

```sh
GROK_ASR_EXPORT=1 grok
```

## What it records

An opt-in agent-session.jsonl sidecar follows the serialized native event writer. It records observed yolo settings, explicit permission decisions and terminal shell outcomes.

Output uses ASR 0.1 with `producer.method: native`. Known credential fields and
recognized secret text are excluded. Keep exports private and review content
before sharing. Pattern filtering cannot identify every secret.

## Limits

Transcript text, tool inputs and outputs, model calls, models and usage are absent. Workspace-hop copies are excluded. Permission events have no call ID or decider. Turn end does not end the session.

The [proposal](PROPOSAL.md) describes the source profile and detailed losses.
Valid ASR does not establish complete source capture.

## Tests and status

Run from the ASR repository root with its Node dependencies installed:

```sh
node upstream/grok-build/check.mjs
node upstream/grok-build/reproduce.mjs /path/to/upstream-checkout
```

The package check verifies file hashes, patch syntax, synthetic source contracts
and ASR sample validation. The reproduce command also replays the series in a
temporary Git index against the pinned source commits. It preserves the source
checkout. It needs both pinned commits in that checkout and does not build or
run the agent. Upstream build and test evidence is in the proposal.

Current project verification and fixture results are in [refresh.json](refresh.json).
No current live inference test is claimed. Historical live evidence does not
certify this refreshed source.
