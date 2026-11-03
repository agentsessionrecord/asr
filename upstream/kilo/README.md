# Kilo Code native ASR export patch

Export saved Kilo sessions for search and audit without starting a model turn.

Upstream: https://github.com/Kilo-Org/kilocode

The pinned base is `25e7fd0574f49eba91ebc5b56b4ed34008aaf323`. The manifest
records the local feature commit, patch digest and all package file digests.
Apply from a separate clean upstream checkout at that base:

```sh
git am "$ASR_PACKAGE"/patches/*.patch
kilo export SESSION_ID --format agent-session
```

Adds ASR to the existing `export` command. The format name and output shape
follow the OpenCode patch. Kilo uses a read-only SQLite transaction instead of
OpenCode's durable-log client. The V2 adapter preserves mixed legacy history in
source order.

The source is retained SQLite V1 and V2 durable events. Manual approvals, served
models, complete settings, media, normalized edits, commits and copied-history
mapping remain incomplete. Unmapped V2 events produce gaps. V2 tool output
currently preserves text only. Known credential filtering does not establish
that an export is safe to share.

Run package checks from the ASR repository root:

```sh
node upstream/kilo/check.mjs
node upstream/kilo/reproduce.mjs /path/to/upstream-checkout
bun upstream/kilo/verify-native.mjs /path/to/upstream-checkout
```

Reproduction compares a temporary Git index with the pinned feature tree. It
preserves the source checkout and does not run a model. The native driver loads
the source exporter, validates a synthetic stream and compares the sample. It
does not exercise an installed full CLI and model session.

Focused native mapping tests, type check, formatting, the shared-source
annotation guard and the CLI build pass. The built binary passes the upstream
smoke checks. Native fixture exports pass the reference validator with zero
errors and zero warnings. [verification.json](verification.json) records the
checked source revision and focused results. See [PROPOSAL.md](PROPOSAL.md) for
the scope.

Current live-model status is unverified. Earlier live evidence is partial and
applies to an older revision. No model run was performed for this refresh.

Submission prerequisites: A linked issue is required. Community reviews are
paused during the V2 migration.
