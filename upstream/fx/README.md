# fx native ASR export

Source: [https://github.com/vercel-labs/fx](https://github.com/vercel-labs/fx).
Pinned base: `e7a69e5cf7da1dace751cfe9038b7a4448e84bcc`.

This patch targets Vercel Labs [fx](https://fx.sh). Build the patched checkout
with the CI-pinned Zig 0.17.0 toolchain, then run the fresh binary:

```sh
./zig-out/bin/fx sessions export --format agent-session --session ID > session.asr.jsonl
```

It reads the existing durable session through the session adapter. Retained text,
runtime instructions, tool steps, raw tool arguments, results, steering boundaries
and interrupted assistant text are exported. Compaction and unavailable active
calls become gaps. Models and usage are not inferred from session totals.
Approvals, settings, timestamps, media and sidecar payloads remain declared losses.
This exporter does not implement a general secret detector. Review all output.

OpenCode sessions imported by the proposed import command retain its text
summaries. The exporter does not reconstruct tools from those summaries.
Native fixture reproduction uses the freshly built binary in a throwaway home:

```sh
python3 upstream/fx/reproduce.py /path/to/patched-checkout
```

## Package checks

The manifest pins the source base, patch commits and file digests. Apply the
ordered patches in a clean checkout at that base with `git am patches/*.patch`.
The package is not installed by the ASR CLI.

From the ASR repository root, run:

```sh
node upstream/fx/check.mjs
node upstream/fx/reproduce.mjs /path/to/patched-checkout
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
