# Crush session export

Export a saved session through `crush session show` so other tools can read it without depending on the private SQLite layout.

The patch adds ASR output to the existing `session show` command. A `.jsonl` output path selects ASR. A `.json` path selects the existing JSON representation. Explicit `--format agent-session` selects ASR on stdout or with any output filename. `--json` and `--format` are mutually exclusive. Files are created with private permissions and existing files are never overwritten.

```sh
crush session show SESSION_ID --format agent-session
crush session show SESSION_ID -o session.asr.jsonl
crush session show SESSION_ID --json -o session.json
```

The exporter reads retained SQLite messages in native row and content order. It keeps text, visible reasoning, calls, and final results. Mutable snapshots cannot recover overwritten events. Media, provider state, approvals, model accounting, settings, file changes, commits, and relationships are declared missing. The export is not a redactor. Review conversation content before sharing.

The patch targets [crush](https://github.com/charmbracelet/crush) at `3b1f8604f0027cf5fa47f29a27655ef1aeed8d8f`. Tests cover exact text, source order, final tool results, and excluded provider state. [TESTS.json](TESTS.json) states which checks ran on this revision.
