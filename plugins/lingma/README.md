# Lingma ASR recorder

This recorder writes one append-only ASR 0.1 file per observed native session.
Python 3.11 or later and a POSIX host are required. The shared
[JSON hook core](../hooks-core/README.md) describes privacy, bounded storage,
receipt order and known losses. No service or model connection is needed.

## Install and uninstall

Run from the repository root. Choose private capture and install directories.
The installer merges its registrations and keeps unrelated hooks and settings.
Close the agent before changing its configuration and restart it after setup.

```sh
python3 plugins/hooks-core/install.py lingma \
  --prefix "$HOME/.local/share/asr-hooks" \
  --config "$HOME/.lingma/settings.json" \
  --output-dir "$HOME/.local/share/asr-captures"
```

Metadata capture is the default. Add `--content full` to retain available text,
input and output with known-secret exclusion. Keep captures private. The content
policy stays fixed for the lifetime of the captured session.

```sh
python3 plugins/hooks-core/install.py lingma \
  --prefix "$HOME/.local/share/asr-hooks" \
  --config "$HOME/.lingma/settings.json" --uninstall
```

Uninstall removes only this install prefix's registrations and keeps captures.
Remove installed files after disabling all agents that share the prefix.

## Mapping and limits

This adapter targets the Lingma settings and JSON stdin contract documented
by Qoder CN IDE. It registers UserPromptSubmit, PreToolUse, PostToolUse,
PostToolUseFailure and Stop. Restart the IDE after changing configuration.

The documented payloads have no call ID. Requests get derived IDs and results
stay unpaired. Successful and failed post callbacks set their stated outcomes.
Available post-tool arguments become effective input. Output stays in metadata
because the contract does not identify its final model-facing form. Tool names
are preserved, including both native names and compatibility names.

The hook surface has no session start or end event. The stream begins with a
gap and has no invented start, initial cwd or end time. Stop preserves available
submission text as an observation. It never ends the session. Approval choices
and outcomes of other hooks are not observable.

The fixed tool-name to ASR kind mapping is in [adapter.json](adapter.json).
Unlisted tool names keep their native spelling without a guessed kind.
The complete common loss list is `LOSSES` in the shared core's `projection.py`.
Adapter-specific losses are in adapter.json. Missing session IDs are never
invented. Hooks read no transcript or global agent configuration. Full-content capture
can observe Git metadata at an explicit new session start.

## Evidence and checks

Supported payload contract: the official documentation checked on 2026-11-01.
No binary compatibility beyond that documented contract is claimed.

- [Qoder CN hooks](https://docs.qoder.cn/user-guide/hooks)

[fixtures/hooks.json](fixtures/hooks.json) contains synthetic native payloads.
These are authored examples from the documented fields. They contain no real
session data. The shared suite checks mappings and native install round trips
and validates every generated ASR stream:

```sh
bash plugins/hooks-core/check.sh
```

Live status: **not live-tested**. This agent needs its own account. No account
was created or used. Synthetic tests establish payload handling only.
