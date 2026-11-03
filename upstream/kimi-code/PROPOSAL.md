# Kimi Code native Agent Session Record export

Export a saved session in an open format that search and code history tools can read. The export keeps the source facts available for later review.

Adds an offline `sessions export` command. It also keeps this command available through the archived CLI entry point.

Applies to [https://github.com/MoonshotAI/kimi-cli](https://github.com/MoonshotAI/kimi-cli) at `9ab1286b8fe4e6bcd116949a27ce5e0ac3389c82`. The local patch commit is `1a1c083f1d10883182229b0001363a115e8d791f`.

Apply the patch with `git am patches/0001-native-agent-session-export.patch` in a clean checkout of that base.

```text
kimi sessions export --session SESSION_ID --format agent-session --output exports
```

It records user text, assistant text, readable reasoning, assembled tool calls, final tool results, approval decisions and observed plan-mode updates. It preserves wire order and exact text. Streamed pieces are folded at their final observation.

It omits opaque signatures, provider replay state, media, instructions, inference accounting, file changes and commits. Unknown prompt authors stay unknown. It does not infer a person or a policy from an approval response. The complete wire log stays available across compaction.

Supported source: the typed Kimi wire JSON Lines format at this revision. Output uses ASR `0.1` and `producer.method: "native"`. File output is exclusive and private where the command writes a file.

Checks: 3 focused pytest tests. Ruff lint and format. Pyright with zero errors and warnings. The included native fixture and sample are synthetic. The sample passes the reference validator with zero errors.

An isolated source CLI run through the local Responses endpoint exported 7 records with zero validator errors or warnings. The installed entry point was also used for export. The retained evidence contains counts and codes only.

`manifest.json` pins the upstream base, local commit and packaged file hashes. Run `node upstream/kimi-code/check.mjs` from the ASR repository to check this patch package without upstream dependencies.

## Verification scope

The live evidence above is from a prior revision. The current source has focused
regressions and package checks. Its full agent and model path has not been rerun.
