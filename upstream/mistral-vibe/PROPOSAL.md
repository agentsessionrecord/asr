# Agent Session Record export for Mistral Vibe

Export a saved session as Agent Session Record so local tools can search and review its recorded work.

This reference implementation exports the public `state` object returned by `session/read`. It uses the app-server snapshot boundary and leaves Runtime-private journals alone. The builtin Vibe reference documents the command.

It preserves public text and readable reasoning in history order. Usable native entry IDs are retained. Harness instruction origins are preserved when stated. In-progress text is marked truncated. A paged or absent history prefix becomes a gap. Known credential text is removed and marked as shortened, with `secrets` listed in missing data.

The supported source is `vibe.public-session-state/v1`. Tool effects, callback events, approvals, accounting, settings, media and other public entry types remain incomplete and are declared. Legacy snapshot timestamps may be synthesized, so record timestamps are omitted. File creation is exclusive with owner-only permissions. No managed-config allowlist changes are needed.

```sh
uv run python -m vibe.app_server.agent_session_export --session state.json --format agent-session --output session.jsonl
```

Source: [mistralai/mistral-vibe](https://github.com/mistralai/mistral-vibe), base `338ad4bf0f73c4dd879d667cf7ab011555ae1751`. Apply the ordered patches in [manifest.json](manifest.json) with `git am` in a clean checkout at that base.

Output uses ASR 0.1 with `producer.method: native`. Known credential fields or recognized secret text are excluded where the source mapping supports them. Review exports before sharing. Filtering cannot identify every secret.

The native fixture and ASR sample are synthetic. [TEST-RESULTS.md](TEST-RESULTS.md) states the current verification results and remaining limits. Structural validation does not prove complete capture.
