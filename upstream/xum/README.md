# Agent Session Record export for Xum

This patch adds an offline ASR export command to [Xum](https://github.com/coder/xum) for one selected chat segment. The pinned base is `7a11fb8cba1afb39f74d268029d449e2d1de9156`. [Apply the patch](../README.md#apply-a-patch) in a clean checkout at that base.

```sh
xum sessions export --session SESSION_ID --source chat.jsonl \
  --format agent-session --output session.asr.jsonl
```

The export keeps retained text, reasoning, final tool snapshots and native message identity with history sequence, and folds replacement snapshots. Tool UI output is kept under `com.coder.xum` metadata. Result status stays unknown because UI output alone does not show that a tool ran successfully. Known credential fields and recognized token strings are left out.

Xum stores history in `~/.xum` or `XUM_ROOT`, split between `chat-archive.jsonl` and `chat.jsonl`. The command reads only the file you select and writes an explicit prefix gap for the earlier part of the chat. It does not discover or join archives, partial files or legacy roots. Models, usage, approvals, settings and tool definitions are declared as losses. Upstream still names the native type `MuxMessage`.

## Checks

```sh
node upstream/xum/check.mjs
node upstream/xum/reproduce.mjs /path/to/patched-checkout
node upstream/xum/reproduce-native.mjs /path/to/patched-checkout
```

See [package checks](../README.md#check-a-package). The third command reproduces the native fixture and needs Bun. Focused project checks and native fixture reproduction pass, and [verification.json](verification.json) has the current status. No live model run covers this revision.
