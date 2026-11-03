# Antigravity ASR recorder

This recorder writes one append-only ASR 0.1 file per observed native session.
Python 3.11 or later and a POSIX host are required. The shared
[JSON hook core](../hooks-core/README.md) describes privacy, bounded storage,
receipt order and known losses. No service or model connection is needed.

## Install and uninstall

Run from the repository root. Choose private capture and install directories.
The installer merges its registrations and keeps unrelated hooks and settings.
Close the agent before changing its configuration and restart it after setup.

```sh
python3 plugins/hooks-core/install.py antigravity \
  --prefix "$HOME/.local/share/asr-hooks" \
  --config "$HOME/.gemini/config/hooks.json" \
  --output-dir "$HOME/.local/share/asr-captures"
```

Metadata capture is the default. Add `--content full` to retain available text,
input and output with known-secret exclusion. Keep captures private. The content
policy stays fixed for the lifetime of the captured session.

```sh
python3 plugins/hooks-core/install.py antigravity \
  --prefix "$HOME/.local/share/asr-hooks" \
  --config "$HOME/.gemini/config/hooks.json" --uninstall
```

Uninstall removes only this install prefix's registrations and keeps captures.
Remove installed files after disabling all agents that share the prefix.

## Mapping and limits

This adapter targets the camelCase stdin contract shared by the Antigravity
App, CLI and IDE. The native configuration contains named groups at the top
level. The installer adds an `asr-session-recorder` group. Tool events use
matcher groups while lifecycle and invocation events use direct handlers.

The contract requires a PreToolUse response. This entry point writes the fixed
response `{"decision":"allow"}` before attempting capture. The reference defines
that value as delegation to the next hook or default policy. It does not bypass
a permission prompt or approve an action. Stop gets `{"decision":""}` and other
events get `{}`. These responses never contain payload text or captured facts.
A recorder error or its deadline does not change the response.

conversationId supplies the native session identity. toolCall contains the
name and arguments. stepIdx is a trajectory position, not a call ID. Requests
therefore get derived IDs and results stay unpaired. PostToolUse's explicit
error string sets failed status when nonempty or completed when empty. An
absent error leaves status unknown. Executed arguments use result input.
The post callback supplies no tool output. Invocation counters are observations
and do not establish model usage, served model or complete inference content.

SessionStart is documented to occur for a new conversation. Stop is an execution
loop boundary and never sets endedAt, even when fullyIdle is true. No SessionEnd
event is documented. Workspace paths are not treated as the initial cwd.

The fixed tool-name to ASR kind mapping is in [adapter.json](adapter.json).
Unlisted tool names keep their native spelling without a guessed kind.
The complete common loss list is `LOSSES` in the shared core's `projection.py`.
Adapter-specific losses are in adapter.json. Missing session IDs are never
invented. Hooks read no transcript or global agent configuration. Full-content capture
can observe Git metadata at an explicit new session start.

## Evidence and checks

Supported payload contract: the official documentation checked on 2026-11-01.
No binary compatibility beyond that documented contract is claimed.

- [Antigravity hooks](https://antigravity.google/docs/hooks)

[fixtures/hooks.json](fixtures/hooks.json) contains synthetic native payloads.
These are authored examples from the documented fields. They contain no real
session data. The shared suite checks mappings and native install round trips
and validates every generated ASR stream:

```sh
bash plugins/hooks-core/check.sh
```

Live status: **not live-tested**. This agent needs its own account. No account
was created or used. Synthetic tests establish payload handling only.
