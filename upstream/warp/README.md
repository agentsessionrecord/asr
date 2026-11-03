# Warp native export patch

## Install

Use a separate writable checkout of the upstream project. The supported base is
`3dca8f995cc116814f17fc818ee0c37ec1141eaa`. [manifest.json](manifest.json) pins
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
cargo run -p persistence --example export_agent_session -- \
  --format agent-session DATABASE CONVERSATION_ID > session.jsonl
```

## What it records

One task in a native SQLite conversation supplies IDs, timestamps, the initial absolute working directory, user and assistant text and retained reasoning.

Output uses ASR 0.1 with `producer.method: native`. The projection excludes opaque provider state. It applies configured upstream
redaction rules and built-in redaction patterns to text and reasoning. Changed
records carry truncation markers and the header declares the loss. A match in
identity or cwd refuses output before any bytes are written. Unknown secrets
still require private review before sharing.

## Limits

Tools, context attachments, settings, approvals, models, usage and relationships are outside this text export. There is no UI action or discovery manifest. No human authorship or end time is inferred.

The [proposal](PROPOSAL.md) describes the source profile and detailed losses.
Valid ASR does not establish complete source capture.

## Tests and status

Run from the ASR repository root with its Node dependencies installed:

```sh
node upstream/warp/check.mjs
node upstream/warp/reproduce.mjs /path/to/upstream-checkout
```

The package check verifies file hashes, patch syntax, synthetic source contracts
and ASR sample validation. The reproduce command also replays the series in a
temporary Git index against the pinned source commits. It preserves the source
checkout. It needs both pinned commits in that checkout and does not build or
run the agent. Upstream build and test evidence is in the proposal.

Current project verification and fixture results are in [refresh.json](refresh.json).
No current live inference test is claimed. Historical live evidence does not
certify this refreshed source.
