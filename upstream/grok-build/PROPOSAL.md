# Grok Build native Agent Session Record export

Export a saved session in an open format that search and code history tools can read. The export keeps the source facts available for later review.

Adds an opt-in live sidecar beside the native `events.jsonl`. The existing serialized event writer also writes `agent-session.jsonl`.

Applies to [https://github.com/xai-org/grok-build](https://github.com/xai-org/grok-build) at `2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8`. The local patch commit is `1747e0cb3a829d7382ebdb697818da77884ad6bb`.

Apply the patch with `git am patches/0001-native-agent-session-export.patch` in a clean checkout of that base.

```text
GROK_ASR_EXPORT=1 grok
```

It records observed yolo-mode settings, explicit permission decisions and terminal shell tool outcomes. It resumes the same native session identity. Workspace-hop copies are excluded. Duplicate terminal results stop the sidecar. Unsafe durations retain their exact spelling in namespaced metadata.

This is a telemetry projection. It does not capture transcript text, tool inputs, tool output, model calls, model identities or usage. A turn ending does not end the session. Permission events lack a call ID and decider. The sample has one expected `unpaired-result` warning because the native terminal event has a call ID but the source log has no call record. No call is invented.

Supported source: Grok event schema 1.0 at this revision. Output uses ASR `0.1` and `producer.method: "native"`. File output is exclusive and private where the command writes a file.

Checks: 19 focused crate tests. Cargo format. Clippy for the affected library and tests with warnings denied. Native EventWriter synthetic fixture. The included native fixture and sample are synthetic. The sample passes the reference validator with zero errors.

Not live-tested. The affected event crate was built and exercised. No patched full CLI binary was available for a model session within this focused crate build. The source supports per-model credentials, so this is not an account-only limitation. Full CLI inference remains unverified.

`manifest.json` pins the upstream base, local commit and packaged file hashes. Run `node upstream/grok-build/check.mjs` from the ASR repository to check this patch package without upstream dependencies.
