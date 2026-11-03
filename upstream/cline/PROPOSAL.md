# Native Agent Session Record export

Export saved Cline sessions in an open schema for search and audit archives.

For [Cline](https://github.com/cline/cline):

```sh
cline history export SESSION_ID --format agent-session
```

Adds one format to the existing history export command. HTML remains the
default. An optional `--output` names a file. Repeated tool results occupy their
final retained position.

The exporter writes ASR 0.1 from the selected local session transcript. It
preserves retained text, reasoning and tool results, declares missing facts and
filters known credentials. Review exports before sharing them.

Approvals, settings, inference boundaries, usage, file edits, commits and
lineage remain missing. Compaction can remove history. Unsafe parsed integers
stop export.

The SDK build, CLI build, CLI type check and Biome check pass. All 47 focused
test cases pass across six files. The session-import file uses a 30-second hook
timeout. Synthetic native fixture exports pass the ASR validator with zero
errors and zero warnings. Tests cover mapping, ordering, corrupt input,
credential filtering and output selection.
