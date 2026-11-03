# OpenClaw ASR export plugin

Source: [https://github.com/openclaw/openclaw](https://github.com/openclaw/openclaw).
Pinned base: `05a73c2679f5c7bb660e5f391ee89dd5e618f565`.

The primary implementation is the independently installable [plugin](plugin/).
It uses only public plugin SDK entry points. No core source patch is needed.
From this package directory, install the local plugin using OpenClaw's plugin CLI:

```sh
openclaw plugins install ./plugin
openclaw asr-export --agent main --session-key SELECTED_KEY \
  --session NATIVE_SESSION_ID --output session.asr.jsonl
```

The command reads the retained public transcript projection. It records text and
tool calls and results. It writes a new file with mode 600. It does not read private
side stores or invent model calls. Known credential fields and signatures are
excluded. Parsed unsafe integers are rejected because exact values are unavailable.
A prefix gap and missing fields describe projection and side-evidence losses.

The eight-commit core series is retained as a secondary implementation. It reads
SQLite snapshots and adds fuller side-store evidence. Apply that series only in
a separate checkout at the pinned base. Its command is:

```sh
openclaw sessions export --format agent-session --session NATIVE_SESSION_ID
```

The secondary path keeps explicit model-call IDs, inclusive usage, offered tools,
reasoning settings, approvals and verified edit receipts where native data permits.
PostgreSQL, cold archives and legacy JSONL import are outside that series.
Neither form supplies a tamper-evident audit chain.

The public projection fixture is `samples/native/plugin-projection.json`.
The secondary fixture remains `samples/native/source.json`.
Run `node --test upstream/openclaw/plugin/transcript.test.mjs` for plugin mapping,
and `node upstream/openclaw/plugin/check-entry.mjs /path/to/upstream-checkout`
to check registration against the public SDK sources.

## Package checks

The manifest pins the source base, patch commits and file digests. Apply the
ordered patches in a clean checkout at that base with `git am patches/*.patch`.
The package is not installed by the ASR CLI.

From the ASR repository root, run:

```sh
node upstream/openclaw/check.mjs
node upstream/openclaw/reproduce.mjs /path/to/patched-checkout
```

The second command checks replay in a temporary Git index. It preserves the
checkout and requires the pinned commits. It does not build the agent.
Native fixture reproduction is a separate check described below.

The refreshed project checks and fixture regeneration are awaiting execution.
See [verification.json](verification.json) for the current status. Existing
live evidence is historical and does not validate this revision. No live model
request was made for this refresh.

Keep exports private and review them before sharing. Pattern filters cannot
identify every secret. Valid ASR does not establish complete capture.
