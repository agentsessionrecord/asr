# Grok Build telemetry export reference

Keep a local structured record of recorded settings and tool outcomes.
This is reference code. Grok Build does not accept outside pull requests or
unsolicited patches.

```sh
GROK_ASR_EXPORT=1 grok
```

The opt-in sidecar follows the serialized `events.jsonl` writer and writes
`agent-session.jsonl`. It records yolo settings, explicit permission decisions
and terminal shell outcomes. It preserves native session identity across resume.
Workspace-hop copies are excluded. Duplicate terminal results stop the sidecar.
A turn ending does not end the session.

Grok's `updates.jsonl` is a separate ACP session update stream.
This patch leaves that stream intact. It does not parse it or infer transcript
messages or calls from telemetry. A complete transcript exporter should use the
store's ACP updates with the [ACP mapping](../../guides/acp.md), fold updates at
completion in stored order and preserve tool IDs. Permission telemetry without
a call ID cannot be joined by tool name. The present patch is not that exporter.

Transcript text, tool input and output, model calls, models and usage are absent.
Permission events do not identify the decider. Unsafe durations retain their
exact value as a string in namespaced metadata. Output is ASR 0.1.
The sample's one `unpaired-result` warning is expected because its telemetry
contains a terminal result but no call. No call is invented.

Source: <https://github.com/xai-org/grok-build> at `2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8`.

Focused verification commands:

```sh
cargo test -p xai-grok-session-events
cargo clippy -p xai-grok-session-events --all-targets -- -D warnings
cargo fmt -p xai-grok-session-events --check
```

Current results and limitations are recorded in [refresh.json](refresh.json).
The fixtures are synthetic. No current live inference test is claimed.
