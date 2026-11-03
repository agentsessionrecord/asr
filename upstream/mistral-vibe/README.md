# Agent Session Record export for Mistral Vibe

Local patch package for [mistralai/mistral-vibe](https://github.com/mistralai/mistral-vibe). The pinned base is `338ad4bf0f73c4dd879d667cf7ab011555ae1751`.

This package is reference code. Mistral Vibe restricts pull requests to maintainers.

## Install

Set `ASR_PACKAGE` to this package's absolute path. In a clean writable checkout at the pinned base, run:

```sh
git am "$ASR_PACKAGE"/patches/*.patch
```

Build and run the project using its own development instructions. These patches are not installed by the ASR CLI.

## Use

```sh
uv run python -m vibe.app_server.agent_session_export --session state.json --format agent-session --output session.jsonl
```

The [proposal](PROPOSAL.md) describes the source mapping and known losses. Exports use ASR 0.1 and the native producer method. Review content before sharing.

## Verification

From the ASR repository root:

```sh
node upstream/mistral-vibe/check.mjs
node upstream/mistral-vibe/reproduce.mjs /path/to/patched-checkout
```

The package check verifies digests, patch syntax, synthetic source contracts and sample validation. Reproduction replays patches in a temporary index and compares the resulting tree with the pinned head. It preserves the source checkout and makes no model requests.

See [TEST-RESULTS.md](TEST-RESULTS.md) for current project checks. Earlier live evidence is partial and predates this refresh. A live run of the refreshed code has not been verified.
