# Agent Session Record export for Grok Build

This reference patch adds an opt-in ASR sidecar to [Grok Build](https://github.com/xai-org/grok-build). Upstream does not accept outside patches. The pinned base is `2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8`. [Apply the patches](../README.md#apply-a-patch) in a clean checkout at that base. The [proposal](PROPOSAL.md) gives runtime requirements and build steps.

```sh
GROK_ASR_EXPORT=1 grok
```

The sidecar, `agent-session.jsonl`, follows the serialized native event writer. It records observed yolo settings, explicit permission decisions and terminal shell outcomes, and leaves out known credential fields and recognized secret text. It has no transcript text, tool inputs or outputs, model calls, models or usage. The ACP transcript in `updates.jsonl` is a separate source. Workspace-hop copies are excluded. Permission events have no call ID or decider, and a turn end does not end the session.

## Checks

```sh
node upstream/grok-build/check.mjs
node upstream/grok-build/reproduce.mjs /path/to/upstream-checkout
```

See [package checks](../README.md#check-a-package). All 20 crate tests, the type check, Clippy and format checks pass, and [refresh.json](refresh.json) has the results. No live model run covers this revision.
