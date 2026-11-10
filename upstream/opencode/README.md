# Agent Session Record export for OpenCode

This patch adds ASR to the format choices of the existing `session export` command in [OpenCode](https://github.com/anomalyco/opencode), so search and audit tools can read recorded sessions. The pinned base is `156bb610108c3da91c6963056f439e2acc1614f0`. [Apply the patch](../README.md#apply-a-patch) in a clean checkout at that base.

```sh
opencode session export SESSION_ID --format agent-session
```

The source is OpenCode's opt-in durable session events, so set `OPENCODE_AGENT_SESSION_HISTORY=1` before recording begins and restart any running server with that setting. Export fails if creation or fork history is missing. Unsupported shell events and content revisions become gaps. Served models, complete approvals, settings, media, edits, commits and lineage stay incomplete. Known credentials are filtered out. See the [proposal](PROPOSAL.md) for the scope.

## Checks

```sh
node upstream/opencode/check.mjs
node upstream/opencode/reproduce.mjs /path/to/upstream-checkout
bun upstream/opencode/verify-native.mjs /path/to/upstream-checkout
```

See [package checks](../README.md#check-a-package) for the first two. `verify-native.mjs` loads the exporter from the patched source, validates a synthetic export and compares it with the sample, without running the installed CLI or a model.

CLI oxlint, 12 focused tests, the CLI type check, the Node bundle build and the documentation type check and build pass. Native fixture exports validate with no errors or warnings. [verification.json](verification.json) records the source revision and results.

On 2026-11-05 the patched CLI, built from source, completed an isolated session with a Claude model through an OpenAI-compatible endpoint, with `OPENCODE_AGENT_SESSION_HISTORY=1` set before recording. The agent read files, edited one and ran a test. Its export validated with 16 records, 0 errors and 0 warnings.

Upstream requires a feature request and design approval before a pull request. Issue #59904 discusses export formats.
