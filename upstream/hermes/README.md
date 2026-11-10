# Agent Session Record export for Hermes

This patch adds ASR to the session export formats of [Hermes](https://github.com/NousResearch/hermes-agent). The pinned base is `b7736eca98cc6919b7b7f1d52dc1c45946793648`. [Apply the patches](../README.md#apply-a-patch) in a clean checkout at that base, then build the project with its own instructions.

```sh
hermes sessions export --format agent-session --session-id SESSION_ID
hermes sessions export exports --format agent-session --session-id SESSION_ID
hermes sessions export exports --format agent-session
```

The [proposal](PROPOSAL.md) describes the source mapping and what the export leaves out.

## Checks

```sh
node upstream/hermes/check.mjs
node upstream/hermes/reproduce.mjs /path/to/patched-checkout
```

See [package checks](../README.md#check-a-package). [TEST-RESULTS.md](TEST-RESULTS.md) has the project check results and the live run. On 2026-11-05 the patched CLI completed an isolated session with a Claude model through an OpenAI-compatible endpoint. The agent read files, edited one and ran a test. Its export validated with 13 records, 0 errors and 0 warnings.
