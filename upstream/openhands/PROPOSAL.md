# Agent Session Record export for OpenHands Canvas

Export a saved session as Agent Session Record so local tools can search and review its recorded work.

This adds **Agent Session Record (.jsonl)** to the existing transcript export dialog in Canvas 1.35.0. It downloads one UTF-8 JSONL file for the selected conversation. Tool details and timestamps are included when available. Presentation filters are disabled for this format.

It uses the existing persisted-history loader and native event types. Messages, tool inputs, model-facing text results and explicit rejection observations retain their source facts. Result updates occupy their final observation. The API orders events by timestamps and exposes no independent recording sequence. This limit is declared as `event_order`.

Usage, model identity, complete approvals and settings, offered tools, media, file edits, commits, lineage and copies remain incomplete. Unmapped events become gaps. Integers outside JavaScript's exact range stop export. The patch stays within the frontend and uses the existing typed export tracking function.

Open a conversation, open transcript export, and select Agent Session Record (.jsonl).

Source: [OpenHands/OpenHands](https://github.com/OpenHands/OpenHands), base `934612b3b6cee05d3a4400b98b48a9c69215401d`. Apply the ordered patches in [manifest.json](manifest.json) with `git am` in a clean checkout at that base.

Output uses ASR 0.1 with `producer.method: native`. Known credential fields or recognized secret text are excluded where the source mapping supports them. Review exports before sharing. Filtering cannot identify every secret.

The native fixture and ASR sample are synthetic. [TEST-RESULTS.md](TEST-RESULTS.md) states the current verification results and remaining limits. Structural validation does not prove complete capture.
