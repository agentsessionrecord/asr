# Mistral Vibe native Agent Session Record export

Export a saved session in an open format that search and code history tools can read. The export keeps the source facts available for later review.

Adds an offline exporter at the public app-server snapshot boundary. The input is the `state` object returned by `session/read`. The builtin Vibe reference documents this command.

Applies to [https://github.com/mistralai/mistral-vibe](https://github.com/mistralai/mistral-vibe) at `338ad4bf0f73c4dd879d667cf7ab011555ae1751`. The local patch commit is `d51f3bceb46c7fd55fb295ebfb54f9d63b7168af`.

Apply the patch with `git am patches/0001-native-agent-session-export.patch` in a clean checkout of that base.

```text
uv run python -m vibe.app_server.agent_session_export --session state.json --format agent-session --output session.asr.jsonl
```

It records public text and readable reasoning in history order, retains usable native entry IDs and preserves known harness instruction origins. In-progress text is marked truncated. A paged or absent history prefix becomes a gap.

It never reads the private Runtime journal. Tool effects, callback events, approvals, accounting, settings, media and other public entry types are omitted and declared. Legacy snapshot timestamps can be synthesized, so all record timestamps are omitted. No managed config allowlist changes are needed.

Supported source: vibe.public-session-state/v1 at this revision. Output uses ASR `0.1` and `producer.method: "native"`. File output is exclusive and private where the command writes a file.

Checks: 2 focused pytest tests. Ruff lint and format. Pyright with zero errors and warnings. The included native fixture and sample are synthetic. The sample passes the reference validator with zero errors.

An isolated app-server JSON-RPC session against a local OpenAI-compatible endpoint reached completed status. Its public snapshot exported 3 records with zero validator errors or warnings. The server was stopped by its own PID. Native IDs were then retained and the synthetic fixture was rechecked.

`manifest.json` pins the upstream base, local commit and packaged file hashes. Run `node upstream/mistral-vibe/check.mjs` from the ASR repository to check this patch package without upstream dependencies.

## Verification scope

The live evidence above is from a prior revision. The current source has focused
regressions and package checks. Its full agent and model path has not been rerun.
