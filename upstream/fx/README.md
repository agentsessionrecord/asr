# Agent Session Record export for fx

This patch adds ASR export to Vercel Labs [fx](https://fx.sh), source at [vercel-labs/fx](https://github.com/vercel-labs/fx). The pinned base is `e7a69e5cf7da1dace751cfe9038b7a4448e84bcc`. [Apply the patches](../README.md#apply-a-patch) in a clean checkout at that base. Build it with the CI-pinned Zig 0.17.0 toolchain, then run the new binary:

```sh
./zig-out/bin/fx sessions export --format agent-session --session ID > session.asr.jsonl
```

The command reads the existing durable session through the session adapter. It exports retained text, runtime instructions, tool steps, raw tool arguments, results, steering boundaries and interrupted assistant text. Compaction and unavailable active calls become gaps. Models and usage are not inferred from session totals. Approvals, settings, timestamps, media and sidecar payloads are declared as losses. There is no general secret detector, so review all output.

The OpenCode import proposed in [fx #1551](https://github.com/vercel-labs/fx/pull/1551) turns tool calls into text summaries. Those stay text on export, and the exporter does not rebuild tools from them.

## Checks

```sh
node upstream/fx/check.mjs
node upstream/fx/reproduce.mjs /path/to/patched-checkout
python3 upstream/fx/reproduce.py /path/to/patched-checkout
```

See [package checks](../README.md#check-a-package). The third command reproduces the native fixture with the freshly built binary in a throwaway home. Focused project checks and native fixture reproduction pass, and [verification.json](verification.json) has the current status. No live model run covers this revision.
