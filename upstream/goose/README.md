# Agent Session Record export for Goose

This patch adds ASR to the `session export` command in [Goose](https://github.com/aaif-goose/goose). The pinned base is `0aa212e61d43e35ee2875ca5aa23c28ebac882c7`. [Apply the patches](../README.md#apply-a-patch) in a clean checkout at that base. The [proposal](PROPOSAL.md) gives runtime requirements, build steps and output options.

```sh
goose session export --format agent-session --session-id SESSION_ID
goose session export --format agent-session --session-id SESSION_ID --output exports
```

The export keeps persisted messages in insertion order, tool calls, final results as the model saw them, reasoning and explicit confirmations. A stored installation namespace keeps native local IDs distinct. Known credential fields and recognized secret text are left out. Usage, model-call boundaries, exit codes, file edits, commits, copies and child sessions are incomplete. Native sanitization and hidden history cannot be reversed, and the command exports one session at a time.

## Checks

```sh
node upstream/goose/check.mjs
node upstream/goose/reproduce.mjs /path/to/upstream-checkout
```

See [package checks](../README.md#check-a-package). Seven export tests, the CLI binary build, type check, Clippy and format checks pass, and [refresh.json](refresh.json) has the results.

On 2026-11-05 the patched CLI completed an isolated session with a Claude model through an OpenAI-compatible endpoint. The agent read files, edited one and ran a test. Its export validated with 12 records, 0 errors and 0 warnings.
