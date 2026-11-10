# Agent Session Record export for Crush

This patch adds ASR output to the existing `session show` command in [Crush](https://github.com/charmbracelet/crush). The pinned base is `3b1f8604f0027cf5fa47f29a27655ef1aeed8d8f`. [Apply the patch](../README.md#apply-a-patch) in a clean checkout at that base. Building needs Go 1.27 or newer.

```sh
crush session show SESSION_ID --format agent-session
crush session show SESSION_ID -o session.asr.jsonl
crush session show SESSION_ID --json -o session.json
```

A `.jsonl` output path selects ASR and a `.json` path selects the existing JSON output. `--format agent-session` selects ASR on stdout or with any file name, and cannot be combined with `--json`. Files are created with private permissions, and existing files are never overwritten.

The exporter reads retained SQLite messages in native row and content order and keeps text, visible reasoning, calls and final results. Mutable snapshots cannot recover overwritten events. Media, provider state, approvals, model accounting, settings, file changes, commits and relationships are declared missing. The export does no redaction, so review the content before sharing.

## Checks

```sh
node upstream/crush/check.mjs
node upstream/crush/reproduce.mjs /path/to/patched-checkout
```

See [package checks](../README.md#check-a-package). The focused upstream checks are `go test ./internal/asr ./internal/cmd`, `go vet ./internal/asr ./internal/cmd` and `go build .`. With a built binary, `python3 upstream/crush/reproduce-native.py /path/to/crush` checks explicit format selection, extension inference and private file output without a model call. [TESTS.json](TESTS.json) records the current scope. No live model run covers this revision.

Charm requires a CLA and a feature discussion before a contribution. The patch follows the command shape requested in discussion #3740 and PR #2609. Markdown export is outside this change.
