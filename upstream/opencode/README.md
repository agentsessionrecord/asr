# OpenCode native ASR export patch

Sessions must be recorded with `OPENCODE_AGENT_SESSION_HISTORY=1` enabled before
recording begins. Restart an existing server with that setting.

## Install

Use a separate writable checkout of the upstream project. The supported base is
`bf5d12c588911a35ec56ad991c3b83cf937f424a`. [manifest.json](manifest.json) pins
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
OPENCODE_AGENT_SESSION_HISTORY=1 opencode serve
opencode session export SESSION_ID --format agent-session
opencode session export SESSION_ID --format agent-session --output new-directory
```

## What it records

Opt-in durable event history supplies messages, reasoning, tools, requested models, usage, native costs and mode and permission changes in recording order. Restart an existing server with history capture enabled.

Output uses ASR 0.1 with `producer.method: native`. Known credential fields and
recognized secret text are excluded. Keep exports private and review content
before sharing. Pattern filtering cannot identify every secret.

## Limits

Missing creation history and fork history fail explicitly. Shell history and content revisions can produce gaps. Served models, complete approvals, settings, file changes, commits, media and lineage remain incomplete.

The [proposal](PROPOSAL.md) describes the source profile and detailed losses.
Valid ASR does not establish complete source capture.

## Tests and status

Run from the ASR repository root with its Node dependencies installed:

```sh
node upstream/opencode/check.mjs
node upstream/opencode/reproduce.mjs /path/to/upstream-checkout
```

The package check verifies file hashes, patch syntax, synthetic source contracts
and ASR sample validation. The reproduce command also replays the series in a
temporary Git index against the pinned source commits. It preserves the source
checkout. It needs both pinned commits in that checkout and does not build or
run the agent. Upstream build and test evidence is in the proposal.

Live-test status: **partial**.
The evidence below is from a prior revision. A live run of the current code has not been verified.
Isolated scratch session through a local OpenAI-compatible endpoint. Native export passed the reference validator with 8 records, zero errors and zero warnings.

The package's [synthetic export](samples/asr/session.jsonl) has zero validator
errors. Any expected extension or pairing warnings are explained by the proposal
or printed by the package check. Package checks make no model requests.
