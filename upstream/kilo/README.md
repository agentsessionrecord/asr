# Agent Session Record export for Kilo Code

This patch adds ASR to the existing `export` command in [Kilo Code](https://github.com/Kilo-Org/kilocode), without starting a model turn. The pinned base is `25e7fd0574f49eba91ebc5b56b4ed34008aaf323`. [Apply the patch](../README.md#apply-a-patch) in a clean checkout at that base.

```sh
kilo export SESSION_ID --format agent-session
```

The format name and output follow the OpenCode patch, but Kilo reads its SQLite store in a read-only transaction instead of using OpenCode's durable-log client. The source is retained V1 and V2 durable events, and the V2 adapter keeps mixed legacy history in source order. Unmapped V2 events become gaps, and V2 tool output keeps text only. Manual approvals, served models, complete settings, media, normalized edits, commits and copied-history mapping are incomplete. Known credentials are filtered out. See the [proposal](PROPOSAL.md) for the scope.

## Checks

```sh
node upstream/kilo/check.mjs
node upstream/kilo/reproduce.mjs /path/to/upstream-checkout
bun upstream/kilo/verify-native.mjs /path/to/upstream-checkout
```

See [package checks](../README.md#check-a-package) for the first two. `verify-native.mjs` loads the exporter from the patched source, validates a synthetic export and compares it with the sample, without running the installed CLI or a model.

Focused native mapping tests, the type check, formatting, the shared-source annotation guard and the CLI build pass, and the built binary passes the upstream smoke checks. Native fixture exports validate with no errors or warnings. [verification.json](verification.json) records the source revision and results. An earlier live run was partial and covered an older revision. No live model run covers this one.

Upstream requires a linked issue, and community reviews are paused during the V2 migration.
