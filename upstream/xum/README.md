# Xum native ASR export

Source: [https://github.com/coder/xum](https://github.com/coder/xum).
Pinned base: `7a11fb8cba1afb39f74d268029d449e2d1de9156`.

The patch adds an offline command for an explicitly selected chat segment.

```sh
xum sessions export --session SESSION_ID --source chat.jsonl \
  --format agent-session --output session.asr.jsonl
```

It keeps retained text, reasoning, final tool snapshots and native message
identity with history sequence. Replacement snapshots are folded.
Tool UI output is retained under `com.coder.xum` metadata. Result status stays
unknown because UI output alone does not establish execution success.
Known credential fields and recognized token strings are excluded.

Current Xum storage uses `~/.xum` or `XUM_ROOT`. Native history combines
`chat-archive.jsonl` with `chat.jsonl`. This command reads only the selected file
and writes an explicit prefix gap. It does not discover or join archives, partial
files or legacy roots. Models, usage, approvals, settings and tool definitions
remain declared losses. The native `MuxMessage` type name is retained upstream.

Native fixture reproduction requires Bun:

```sh
node upstream/xum/reproduce-native.mjs /path/to/patched-checkout
```

## Package checks

The manifest pins the source base, patch commits and file digests. Apply the
ordered patches in a clean checkout at that base with `git am patches/*.patch`.
The package is not installed by the ASR CLI.

From the ASR repository root, run:

```sh
node upstream/xum/check.mjs
node upstream/xum/reproduce.mjs /path/to/patched-checkout
```

The second command checks replay in a temporary Git index. It preserves the
checkout and requires the pinned commits. It does not build the agent.
Native fixture reproduction is a separate check described below.

Focused project checks and synthetic native fixture reproduction pass.
See [verification.json](verification.json) for the current status. Existing
live evidence is historical and does not validate this revision. No live model
request was made for this refresh.

Keep exports private and review them before sharing. Pattern filters cannot
identify every secret. Valid ASR does not establish complete capture.
