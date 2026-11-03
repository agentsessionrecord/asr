# fx native ASR export

Export a retained fx session as ASR so users can read it in other session tools.
The command adds `fx sessions export --format agent-session --session ID` to the
existing sessions command table. It reads the existing session store and writes
JSON Lines to standard output. It adds no persistence or dependencies.

The session module owns a typed `render` function over `DurableSessionState`.
It preserves retained text, runtime context, tool steps, raw argument text and
result status. Compacted history and unavailable interrupted calls become gaps.
It does not infer model calls or usage from session totals. Approvals, settings,
timestamps and sidecar payloads remain declared losses.

The command shares the existing session adapter with conversion and import.
The OpenCode import proposal in [#1551](https://github.com/vercel-labs/fx/pull/1551)
turns tool calls into text summaries. Those summaries stay text on export.
Native fx tool steps keep their structured call and result mapping.

The owner remains the session module, with CLI argument handling in the existing
CLI surface. JSON Lines is the only new format. Focused session tests own mapping
coverage. Existing session end-to-end tests own command behavior. Build with the
CI-pinned Zig 0.17.0 and run `zig build test-agent-session`, format checks and the
native fixture reproduction. Exact-head Linux and macOS CI remains required.

## Docs

Add this command to the sessions manual:

```sh
fx sessions export --format agent-session --session ID > session.asr.jsonl
```

The file contains retained session facts and explicit gaps. It is not a restorable
fx session and does not contain complete compacted history. Review it before sharing.

Source: [https://github.com/vercel-labs/fx](https://github.com/vercel-labs/fx).
Base: `e7a69e5cf7da1dace751cfe9038b7a4448e84bcc`.
