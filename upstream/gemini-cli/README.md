# Gemini CLI native ASR export patch

Export saved Gemini CLI sessions for tools that need an open, ordered record.

Upstream: https://github.com/google-gemini/gemini-cli

The pinned base is `203fbc528d83982a7866da43e989b69dd089de83`. The manifest
records the local feature commit, patch digest and all package file digests.
Apply from a separate clean upstream checkout at that base:

```sh
git am "$ASR_PACKAGE"/patches/*.patch
gemini sessions export --format agent-session --session SESSION_ID
```

Adds an offline `sessions export` subcommand. Updated messages and results
occupy their final saved position. Unknown content parts stay in namespaced
metadata.

The source is saved native JSONL recordings. Approvals, settings, model
accounting, edits, commits, tool definitions, instructions and lineage remain
incomplete. Multiple recording segments need explicit selection. Input is held
in memory. Known credential filtering does not establish that an export is safe
to share.

Run package checks from the ASR repository root:

```sh
node upstream/gemini-cli/check.mjs
node upstream/gemini-cli/reproduce.mjs /path/to/upstream-checkout
bun upstream/gemini-cli/verify-native.mjs /path/to/upstream-checkout
```

Reproduction compares a temporary Git index with the pinned feature tree. It
preserves the source checkout and does not run a model. The native driver loads
the source exporter, validates a synthetic stream and compares the sample. It
does not exercise an installed full CLI and model session.

The workspace build, 11 focused export tests, CLI type check and focused ESLint
pass. Validation used npm 11, which supports the repository's dependency alias
overrides. Native fixture exports pass the reference validator with zero errors
and zero warnings. [verification.json](verification.json) records the checked
source revision and focused results. See [PROPOSAL.md](PROPOSAL.md) for the
scope.

Current live-model status is unverified. Earlier live evidence is partial and
applies to an older revision. No model run was performed for this refresh.

Submission prerequisites: Google CLA and an approved feature issue are required
before submission. The team is focused on maintenance.
