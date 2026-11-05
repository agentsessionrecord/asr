# OpenCode native ASR export patch

Export recorded OpenCode sessions in a format that search and audit tools can
read.

Upstream: https://github.com/anomalyco/opencode

The pinned base is `156bb610108c3da91c6963056f439e2acc1614f0`. The manifest
records the local feature commit, patch digest and all package file digests.
Apply from a separate clean upstream checkout at that base:

```sh
git am "$ASR_PACKAGE"/patches/*.patch
opencode session export SESSION_ID --format agent-session
```

Adds ASR to the existing `session export` format selector. Capture requires
`OPENCODE_AGENT_SESSION_HISTORY=1` before recording begins. Restart an existing
server with this setting.

The source is opt-in durable session events. Missing creation or fork history
fails explicitly. Unsupported shell events and content revisions produce gaps.
Served models, complete approvals, settings, media, edits, commits and lineage
remain incomplete. Known credential filtering does not establish that an export
is safe to share.

Run package checks from the ASR repository root:

```sh
node upstream/opencode/check.mjs
node upstream/opencode/reproduce.mjs /path/to/upstream-checkout
bun upstream/opencode/verify-native.mjs /path/to/upstream-checkout
```

Reproduction compares a temporary Git index with the pinned feature tree. It
preserves the source checkout and does not run a model. The native driver loads
the source exporter, validates a synthetic stream and compares the sample. It
does not exercise an installed full CLI and model session.

CLI oxlint, 12 focused tests, CLI type check, the Node bundle build and
documentation type check and build pass. Native fixture exports pass the
reference validator with zero errors and zero warnings.
[verification.json](verification.json) records the checked source revision and
focused results. See [PROPOSAL.md](PROPOSAL.md) for the scope.

On 2026-11-05 the patched source CLI completed an isolated session with a Claude
model through an OpenAI-compatible endpoint, with
`OPENCODE_AGENT_SESSION_HISTORY=1` set before recording. The agent read files,
edited one and ran a test. Its export validated with 16 records, 0 errors and 0
warnings. [verification.json](verification.json) records the counts.

Submission prerequisites: Feature request and design approval are required
before submission. Issue #59904 is discussing export formats.
