# Codex native export design feedback

Read the [proposal](PROPOSAL.md) for the design and user benefit.
Codex [contribution policy](https://github.com/openai/codex/blob/main/docs/contributing.md)
says it does not accept external code contributions or pull requests. The local
series is reference material for design feedback. Regenerate the Cargo lockfile
hunks with upstream tooling when evaluating another base.

## Evaluate the reference implementation

Use a separate writable checkout of the upstream project. The supported base is
`6b2a2757de696c2506ee460c49c66a8e2bed65e0`. [manifest.json](manifest.json) pins
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

## Proposed CLI

The reference implementation demonstrates these commands. Replace example IDs
and paths with a synthetic session when evaluating it locally. See the proposal
for selection and output options.

```sh
codex sessions export --format agent-session --all --output ./asr
codex sessions export --format agent-session --session NATIVE_THREAD_ID
codex sessions register
```

## What it records

Saved rollouts and a read-only state snapshot supply messages, tools, settings, offered tools, approvals, model calls, usage and structured file changes. Mutable titles and pull request links use separate annotations.

Output uses ASR 0.1 with `producer.method: native`. Known credential fields and
recognized secret text are excluded. Keep exports private and review content
before sharing. Pattern filtering cannot identify every secret.

## Limits

The source does not establish every served model, approval, file edit, commit, setting or copied-history boundary. Attachments and current Git state are not read to fill losses.

The [proposal](PROPOSAL.md) describes the source profile and detailed losses.
Valid ASR does not establish complete source capture.

## Tests and status

Run from the ASR repository root with its Node dependencies installed:

```sh
node upstream/codex/check.mjs
node upstream/codex/reproduce.mjs /path/to/upstream-checkout
```

The package check verifies file hashes, patch syntax, synthetic source contracts
and ASR sample validation. The reproduce command also replays the series in a
temporary Git index against the pinned source commits. It preserves the source
checkout. It needs both pinned commits in that checkout and does not build or
run the agent. Upstream build and test evidence is in the proposal.

Current project verification and fixture results are in [refresh.json](refresh.json).
No current live inference test is claimed. Historical live evidence does not
certify this refreshed source.
