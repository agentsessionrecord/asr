# Crush ASR export

The patch adds ASR output to the existing `session show` command. A `.jsonl` output path selects ASR. A `.json` path selects the existing JSON representation. Explicit `--format agent-session` selects ASR on stdout or with any output filename. `--json` and `--format` are mutually exclusive. Files are created with private permissions and existing files are never overwritten.

Source: https://github.com/charmbracelet/crush. Pinned base: `3b1f8604f0027cf5fa47f29a27655ef1aeed8d8f`.

Apply `patches/*.patch` with `git am` in a clean writable checkout at the pinned base. Build the patched source using its own instructions.

```sh
crush session show SESSION_ID --format agent-session
crush session show SESSION_ID -o session.asr.jsonl
crush session show SESSION_ID --json -o session.json
```

The exporter reads retained SQLite messages in native row and content order. It keeps text, visible reasoning, calls, and final results. Mutable snapshots cannot recover overwritten events. Media, provider state, approvals, model accounting, settings, file changes, commits, and relationships are declared missing. The export is not a redactor. Review conversation content before sharing.

Go 1.27 or newer is required. Focused checks are `go test ./internal/asr ./internal/cmd`, `go vet ./internal/asr ./internal/cmd`, and `go build .`. With a built binary, `python3 upstream/crush/reproduce-native.py /path/to/crush` exercises explicit format selection, extension inference, and private file output without a model call.

Run these package checks from the ASR repository:

```sh
node upstream/crush/check.mjs
node upstream/crush/reproduce.mjs /path/to/patched-checkout
```

Package reproduction replays the patch in a temporary Git index. It preserves the checkout and does not compile the agent. [TESTS.json](TESTS.json) records the current verification scope. No current model session was run.

Charm requires a CLA and feature discussion before a contribution. The patch follows the existing command shape requested in discussion #3740 and PR #2609. Markdown export is outside this change.
