# Agent Session Record export for OpenClaw

This package adds ASR export to [OpenClaw](https://github.com/openclaw/openclaw). The pinned base is `05a73c2679f5c7bb660e5f391ee89dd5e618f565`.

## Plugin

The main implementation is a standalone [plugin](plugin/) that uses only public plugin SDK entry points, so OpenClaw core needs no patch. Review the plugin source, then install it from this directory with OpenClaw's plugin CLI. The flags confirm that you reviewed the local source and accept the plugin's capabilities.

```sh
openclaw plugins install --force --accept-capabilities ./plugin
openclaw asr-export --agent main --session-key SELECTED_KEY \
  --session NATIVE_SESSION_ID --output session.asr.jsonl
```

The command reads the retained public transcript projection and records text, tool calls and results. It writes a new file with mode 600. It does not read private side stores or invent model calls. Known credential fields and signatures are left out, and parsed unsafe integers are rejected because their exact values are lost. A prefix gap and missing fields declare what the projection and side evidence lack.

## Core patch series

The eight-commit core series is kept as a secondary implementation. It reads SQLite snapshots and adds fuller side-store evidence. [Apply it](../README.md#apply-a-patch) only in a separate checkout at the pinned base.

```sh
openclaw sessions export --format agent-session --session NATIVE_SESSION_ID
```

It keeps explicit model-call IDs, inclusive usage, offered tools, reasoning settings, approvals and verified edit receipts where native data allows. PostgreSQL, cold archives and legacy JSONL import are outside the series. Neither form gives a tamper-evident audit chain.

## Checks

```sh
node upstream/openclaw/check.mjs
node upstream/openclaw/reproduce.mjs /path/to/patched-checkout
node --test upstream/openclaw/plugin/transcript.test.mjs
node upstream/openclaw/plugin/check-entry.mjs /path/to/upstream-checkout
```

See [package checks](../README.md#check-a-package). The third command tests the plugin mapping and the fourth checks its registration against the built public SDK. The plugin fixture is `samples/native/plugin-projection.json` and the core series fixture is `samples/native/source.json`.

The full build, focused tests, source lint, core type check, format check and synthetic native exports pass. Local plugin install and selected-session export also pass with isolated configuration. The full project check passes its preflight and type checks, but full lint fails on 20 line-limit errors in unchanged upstream files. [verification.json](verification.json) lists those paths and the current status. No live model run covers this revision.
