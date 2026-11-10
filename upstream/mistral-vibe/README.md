# Agent Session Record export for Mistral Vibe

This reference patch adds ASR export of saved sessions to [Mistral Vibe](https://github.com/mistralai/mistral-vibe). Upstream accepts pull requests only from maintainers. The pinned base is `338ad4bf0f73c4dd879d667cf7ab011555ae1751`. [Apply the patches](../README.md#apply-a-patch) in a clean checkout at that base, then build the project with its own instructions.

```sh
uv run python -m vibe.app_server.agent_session_export --session state.json --format agent-session --output session.jsonl
```

The [proposal](PROPOSAL.md) describes the source mapping and what the export leaves out.

## Checks

```sh
node upstream/mistral-vibe/check.mjs
node upstream/mistral-vibe/reproduce.mjs /path/to/patched-checkout
```

See [package checks](../README.md#check-a-package). [TEST-RESULTS.md](TEST-RESULTS.md) has the project check results. An earlier live run was partial and covered an older revision. No live model run covers this one.
