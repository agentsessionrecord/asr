# Native Agent Session Record export

Export recorded OpenCode sessions in a format that search and audit tools can
read.

Adds ASR to the existing `session export` format selector. Capture requires
`OPENCODE_AGENT_SESSION_HISTORY=1` before recording begins.
Restart an existing server with that setting.

For [OpenCode](https://github.com/anomalyco/opencode):

```sh
opencode session export SESSION_ID --format agent-session
```

The exporter writes ASR 0.1 from opt-in durable session events. It preserves
retained text, reasoning and tool results, declares missing facts and filters
known credentials. Review exports before sharing them.

Missing creation or fork history fails explicitly. Unsupported shell events and
content revisions produce gaps. Served models, complete approvals, settings,
media, edits, commits and lineage remain incomplete.

CLI oxlint, 12 focused tests, CLI type check, the Node bundle build and
documentation type check and build pass. Synthetic native fixture exports pass
the ASR validator with zero errors and zero warnings. Tests cover mapping,
ordering, corrupt input, credential filtering and output selection.
