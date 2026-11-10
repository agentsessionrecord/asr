# Agent Session Record export for Deep Agents Code

This patch adds ASR export of saved threads to Deep Agents Code in [langchain-ai/deepagents](https://github.com/langchain-ai/deepagents). The pinned base is `89f85affc20ea22d9a1ddb5821987660368b7b8b`. [Apply the patches](../README.md#apply-a-patch) in a clean checkout at that base, then build the project with its own instructions.

```sh
dcode threads export --format agent-session --session THREAD_ID
dcode threads export --format agent-session --session THREAD_ID --output exports
```

The [proposal](PROPOSAL.md) describes the source mapping and what the export leaves out.

## Checks

```sh
node upstream/deepagents/check.mjs
node upstream/deepagents/reproduce.mjs /path/to/patched-checkout
```

See [package checks](../README.md#check-a-package). [TEST-RESULTS.md](TEST-RESULTS.md) has the project check results. An earlier live run was partial and covered an older revision. No live model run covers this one.
