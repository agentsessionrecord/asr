# Kiro ASR recorder

This recorder writes one append-only ASR 0.1 file per observed native session.
Python 3.11 or later and a POSIX host are required. The shared
[JSON hook core](../hooks-core/README.md) describes privacy, bounded storage,
receipt order and known losses. No service or model connection is needed.

## Install and uninstall

Run from the repository root. Choose private capture and install directories.
The installer merges its registrations and keeps unrelated hooks and settings.
Close the agent before changing its configuration and restart it after setup.

```sh
python3 plugins/hooks-core/install.py kiro \
  --prefix "$HOME/.local/share/asr-hooks" \
  --config "$HOME/.kiro/hooks/asr-recorder.json" \
  --output-dir "$HOME/.local/share/asr-captures"
```

Metadata capture is the default. Add `--content full` to retain available text,
input and output with known-secret exclusion. Keep captures private. The content
policy stays fixed for the lifetime of the captured session.

```sh
python3 plugins/hooks-core/install.py kiro \
  --prefix "$HOME/.local/share/asr-hooks" \
  --config "$HOME/.kiro/hooks/asr-recorder.json" --uninstall
```

Uninstall removes only this install prefix's registrations and keeps captures.
Remove installed files after disabling all agents that share the prefix.

## Mapping and limits

This adapter targets standalone `version: "v1"` hook files in Kiro IDE 1.0
and CLI V3. The installer uses the native `hooks` array with `trigger`, `action`,
`timeout` in seconds and `enabled`. It preserves unrelated entries. Legacy
CLI 2.x profiles and Web sessions are outside this contract. Web stores hook
configuration but does not execute these triggers.

The recorded triggers are SessionStart, UserPromptSubmit, PreToolUse,
PostToolUse, Stop, file triggers and task triggers. SessionEnd is registered
for CLI V3 only. The IDE does not dispatch it. File and task triggers are kept
as observations. They do not establish applied file content or task outcomes.

Tool callbacks expose no documented call ID. Requests get derived IDs and
results stay unpaired. PostToolUse alone does not state success, so status
stays unknown. Available post-tool input is retained as effective input and
structured output stays in metadata. Stop never sets an end time. No approval
choice is inferred from a tool outcome or a callback's exit code.

The fixed tool-name to ASR kind mapping is in [adapter.json](adapter.json).
Unlisted tool names keep their native spelling without a guessed kind.
The complete common loss list is `LOSSES` in the shared core's `projection.py`.
Adapter-specific losses are in adapter.json. Missing session IDs are never
invented. Hooks read no transcript or global agent configuration. Full-content capture
can observe Git metadata at an explicit new session start.

## Evidence and checks

Supported payload contract: the official documentation checked on 2026-11-01.
No binary compatibility beyond that documented contract is claimed.

- [Hooks](https://kiro.dev/docs/hooks/)
- [Types](https://kiro.dev/docs/hooks/types/)
- [Actions](https://kiro.dev/docs/hooks/actions/)
- [V3 migration](https://kiro.dev/docs/cli/v3/hooks-migration/)

[fixtures/hooks.json](fixtures/hooks.json) contains synthetic native payloads.
These are authored examples from the documented fields. They contain no real
session data. The shared suite checks mappings and native install round trips
and validates every generated ASR stream:

```sh
bash plugins/hooks-core/check.sh
```

Live status: **not live-tested**. This agent needs its own account. No account
was created or used. Synthetic tests establish payload handling only.
