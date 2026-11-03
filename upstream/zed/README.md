# Zed native export patch

## Install

Use a separate writable checkout of the upstream project. The supported base is
`57dfd54adebb6d4a62cd1c42d397acb667a71c0a`. [manifest.json](manifest.json) pins
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
cargo run -p agent --example export_agent_session -- \
  --format agent-session SESSION_ID THREAD.json > session.jsonl
```

## What it records

A saved native DbThread JSON snapshot supplies retained text, reasoning, calls, structured or raw arguments, results and native user message IDs. Supply the separate database thread ID.

Output uses ASR 0.1 with `producer.method: native`. The projection excludes opaque provider state. It does not provide a general
secret-redaction service. Keep exports private and review content before sharing.

## Limits

Images, models, usage, approvals, settings, relationships and event times are absent. Result map order does not establish execution order. No GUI action or native database discovery is added. The upstream review marker still requires human review.

The [proposal](PROPOSAL.md) describes the source profile and detailed losses.
Valid ASR does not establish complete source capture.

## Tests and status

Run from the ASR repository root with its Node dependencies installed:

```sh
node upstream/zed/check.mjs
node upstream/zed/reproduce.mjs /path/to/upstream-checkout
```

The package check verifies file hashes, patch syntax, synthetic source contracts
and ASR sample validation. The reproduce command also replays the series in a
temporary Git index against the pinned source commits. It preserves the source
checkout. It needs both pinned commits in that checkout and does not build or
run the agent. Upstream build and test evidence is in the proposal.

Current project verification and fixture results are in [refresh.json](refresh.json).
No current live inference test is claimed. Historical live evidence does not
certify this refreshed source.
