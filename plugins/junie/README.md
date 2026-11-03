# Junie CLI ASR recorder

This recorder writes one append-only ASR 0.1 file per observed native session.
Python 3.11 or later and a POSIX host are required. The shared
[JSON hook core](../hooks-core/README.md) describes privacy, bounded storage,
receipt order and known losses. No service or model connection is needed.

## Install and uninstall

Run from the repository root. Choose private capture and install directories.
The installer merges its registrations and keeps unrelated hooks and settings.
Close the agent before changing its configuration and restart it after setup.

```sh
python3 plugins/hooks-core/install.py junie \
  --prefix "$HOME/.local/share/asr-hooks" \
  --config "$HOME/.junie/config.json" \
  --output-dir "$HOME/.local/share/asr-captures"
```

Metadata capture is the default. Add `--content full` to retain available text,
input and output with known-secret exclusion. Keep captures private. The content
policy stays fixed for the lifetime of the captured session.

```sh
python3 plugins/hooks-core/install.py junie \
  --prefix "$HOME/.local/share/asr-hooks" \
  --config "$HOME/.junie/config.json" --uninstall
```

Uninstall removes only this install prefix's registrations and keeps captures.
Remove installed files after disabling all agents that share the prefix.

## Mapping and limits

This adapter targets the documented Junie CLI Early Access hook contract.
Install into user configuration or a file explicitly selected with
`--config-location`. Junie ignores default project-local hook configuration.
ACP and server hosts do not provide the documented full callback surface.

All installed handlers use `async: true`. This makes them advisory and prevents
them from approving or denying an action. A synchronous PermissionRequest hook
that exits successfully can automatically approve the action even with no
output. Do not remove the async setting. The recorder returns no decision.

Junie's examples omit session_id on PreToolUse, PermissionRequest, Stop,
StopFailure and SessionEnd. Stop is explicitly documented to lack identity.
Those payloads are skipped. If a callback supplies a native session_id, the
adapter can record it. It never recovers identity from the last active session,
working directory or transcript. The fixtures retain the documented omissions
and test that no session is invented. Capture is therefore limited even when
the native hook ran. These losses are declared as `sessionless_callbacks`.

No post-tool callback is documented. Results, effective input, approval choices
and hook outcomes remain missing. Startup and clear start receipts can set
startedAt. Resume and compact do not establish the original start or lineage.
Async process scheduling can reorder receipts. Only an identity-bearing explicit
SessionEnd can set endedAt. StopFailure is an observation, not a model call.

The fixed tool-name to ASR kind mapping is in [adapter.json](adapter.json).
Unlisted tool names keep their native spelling without a guessed kind.
The complete common loss list is `LOSSES` in the shared core's `projection.py`.
Adapter-specific losses are in adapter.json. Missing session IDs are never
invented. Hooks read no transcript or global agent configuration. Full-content capture
can observe Git metadata at an explicit new session start.

## Evidence and checks

Supported payload contract: the official documentation checked on 2026-11-01.
No binary compatibility beyond that documented contract is claimed.

- [Junie CLI hooks](https://junie.jetbrains.com/docs/junie-cli-hooks.html)
- [Provider and environment settings](https://junie.jetbrains.com/docs/environment-variables.html)

[fixtures/hooks.json](fixtures/hooks.json) contains synthetic native payloads.
These are authored examples from the documented fields. They contain no real
session data. The shared suite checks mappings and native install round trips
and validates every generated ASR stream:

```sh
bash plugins/hooks-core/check.sh
```

Live status: **not live-tested**. Junie documents a custom LiteLLM proxy and
BYOK route, but no executable was available for an isolated run. Existing local
version resources contain documentation and skills only. No account was created
or used. Synthetic tests establish payload handling only.
