# Agent Session Record export for Gemini CLI

This patch adds an offline `sessions export` subcommand to [Gemini CLI](https://github.com/google-gemini/gemini-cli) that writes saved sessions as ASR, for tools that need an open, ordered copy. The pinned base is `203fbc528d83982a7866da43e989b69dd089de83`. [Apply the patch](../README.md#apply-a-patch) in a clean checkout at that base.

```sh
gemini sessions export --format agent-session --session SESSION_ID
```

The source is Gemini CLI's saved native JSONL recordings. Updated messages and results sit at their final saved position, and unknown content parts stay in namespaced metadata. Approvals, settings, model accounting, edits, commits, tool definitions, instructions and lineage are incomplete. A session with several recording segments needs explicit selection, and input is held in memory. Known credentials are filtered out. See the [proposal](PROPOSAL.md) for the scope.

## Checks

```sh
node upstream/gemini-cli/check.mjs
node upstream/gemini-cli/reproduce.mjs /path/to/upstream-checkout
bun upstream/gemini-cli/verify-native.mjs /path/to/upstream-checkout
```

See [package checks](../README.md#check-a-package) for the first two. `verify-native.mjs` loads the exporter from the patched source, validates a synthetic export and compares it with the sample, without running the installed CLI or a model.

The workspace build, 11 focused export tests, the CLI type check and focused ESLint pass. Validation used npm 11, which supports the repository's dependency alias overrides. Native fixture exports validate with no errors or warnings. [verification.json](verification.json) records the source revision and results. An earlier live run was partial and covered an older revision. No live model run covers this one.

Upstream requires the Google CLA and an approved feature issue before a pull request. The team is focused on maintenance.
