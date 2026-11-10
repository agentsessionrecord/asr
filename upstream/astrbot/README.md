# Agent Session Record export for AstrBot

This patch adds ASR export of saved conversations to [AstrBot](https://github.com/AstrBotDevs/AstrBot). The pinned base is `f926af99ec5f8bd85b64413f8bfad55da76ef73b`. [Apply the patches](../README.md#apply-a-patch) in a clean checkout at that base, then build the project with its own instructions.

```sh
astrbot sessions export --format agent-session --session CONVERSATION_ID
astrbot sessions export --format agent-session --output exports
```

The [proposal](PROPOSAL.md) describes the source mapping and what the export leaves out.

## Checks

```sh
node upstream/astrbot/check.mjs
node upstream/astrbot/reproduce.mjs /path/to/patched-checkout
```

See [package checks](../README.md#check-a-package). [TEST-RESULTS.md](TEST-RESULTS.md) has the project check results. An earlier live run was partial and covered an older revision. No live model run covers this one.
