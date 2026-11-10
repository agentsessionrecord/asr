# Agent Session Record export for Cline

This patch adds ASR as a format of the existing history export command in [Cline](https://github.com/cline/cline). HTML stays the default, and an optional `--output` names a file. The pinned base is `a542151bb737e25eb332d34c647ab4b9d99dd98b`. [Apply the patch](../README.md#apply-a-patch) in a clean checkout at that base.

```sh
cline history export SESSION_ID --format agent-session
```

The source is the selected local session transcript. A tool result that repeats sits at its final retained position. Approvals, settings, inference boundaries, usage, file edits, commits and lineage are missing, and compaction can remove history. Unsafe parsed integers stop the export. Known credentials are filtered out. See the [proposal](PROPOSAL.md) for the scope.

## Checks

```sh
node upstream/cline/check.mjs
node upstream/cline/reproduce.mjs /path/to/upstream-checkout
bun upstream/cline/verify-native.mjs /path/to/upstream-checkout
```

See [package checks](../README.md#check-a-package) for the first two. `verify-native.mjs` loads the exporter from the patched source, validates a synthetic export and compares it with the sample, without running the installed CLI or a model.

The SDK build, CLI build, CLI type check and Biome check pass, as do all 47 focused test cases across six files. The session import test file uses a 30-second hook timeout. Native fixture exports validate with no errors or warnings. [verification.json](verification.json) records the source revision and results. An earlier live run was partial and covered an older revision. No live model run covers this one.

Upstream requires an approved feature request before a pull request.
