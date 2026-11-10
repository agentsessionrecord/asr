# Agent Session Record export for OpenHands Canvas

This patch adds ASR to the transcript export dialog of [OpenHands](https://github.com/OpenHands/OpenHands) Canvas 1.35.0. The pinned base is `934612b3b6cee05d3a4400b98b48a9c69215401d`. [Apply the patches](../README.md#apply-a-patch) in a clean checkout at that base, then build the project with its own instructions.

To export, open a conversation, open transcript export and select Agent Session Record (.jsonl). The [proposal](PROPOSAL.md) describes the source mapping and what the export leaves out.

## Checks

```sh
node upstream/openhands/check.mjs
node upstream/openhands/reproduce.mjs /path/to/patched-checkout
```

See [package checks](../README.md#check-a-package). [TEST-RESULTS.md](TEST-RESULTS.md) has the project check results. A Canvas end-to-end run has not been done. An earlier live run was partial and covered an older revision. No live model run covers this one.
