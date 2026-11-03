# Native Agent Session Record export

Export saved Kilo sessions for search and audit without starting a model turn.

For [Kilo Code](https://github.com/Kilo-Org/kilocode):

```sh
kilo export SESSION_ID --format agent-session
```

Adds ASR to the existing `export` command. The format name and output shape
follow the OpenCode patch. Kilo uses a read-only SQLite transaction instead of
OpenCode's durable-log client. The V2 adapter preserves mixed legacy history in
source order.

The exporter writes ASR 0.1 from retained SQLite V1 and V2 durable events. It
preserves retained text, reasoning and tool results, declares missing facts and
filters known credentials. Review exports before sharing them.

Manual approvals, served models, complete settings, media, normalized edits,
commits and copied-history mapping remain incomplete. Unmapped V2 events produce
gaps. V2 tool output currently preserves text only.

Focused native mapping tests, type check, formatting, the shared-source
annotation guard and the CLI build pass. The built binary passes the upstream
smoke checks. Synthetic native fixture exports pass the ASR validator with zero
errors and zero warnings. Tests cover mapping, ordering, corrupt input,
credential filtering and output selection.
