# Cline native ASR export patch

Export saved Cline sessions in an open schema for search and audit archives.

Upstream: https://github.com/cline/cline

The pinned base is `a542151bb737e25eb332d34c647ab4b9d99dd98b`. The manifest
records the local feature commit, patch digest and all package file digests.
Apply from a separate clean upstream checkout at that base:

```sh
git am "$ASR_PACKAGE"/patches/*.patch
cline history export SESSION_ID --format agent-session
```

Adds one format to the existing history export command. HTML remains the
default. An optional `--output` names a file. Repeated tool results occupy their
final retained position.

The source is the selected local session transcript. Approvals, settings,
inference boundaries, usage, file edits, commits and lineage remain missing.
Compaction can remove history. Unsafe parsed integers stop export. Known
credential filtering does not establish that an export is safe to share.

Run package checks from the ASR repository root:

```sh
node upstream/cline/check.mjs
node upstream/cline/reproduce.mjs /path/to/upstream-checkout
bun upstream/cline/verify-native.mjs /path/to/upstream-checkout
```

Reproduction compares a temporary Git index with the pinned feature tree. It
preserves the source checkout and does not run a model. The native driver loads
the source exporter, validates a synthetic stream and compares the sample. It
does not exercise an installed full CLI and model session.

The SDK build, CLI build, CLI type check and Biome check pass. All 47 focused
test cases pass across six files. The session-import file uses a 30-second hook
timeout. Native fixture exports pass the reference validator with zero errors
and zero warnings. [verification.json](verification.json) records the checked
source revision and focused results. See [PROPOSAL.md](PROPOSAL.md) for the
scope.

Current live-model status is unverified. Earlier live evidence is partial and
applies to an older revision. No model run was performed for this refresh.

Submission prerequisites: An approved feature request is required before
submission.
