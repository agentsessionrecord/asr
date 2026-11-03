# Firebender ASR recorder

This recorder writes one append-only ASR 0.1 file per observed native session.
Python 3.11 or later and a POSIX host are required. The shared
[JSON hook core](../hooks-core/README.md) describes privacy, bounded storage,
receipt order and known losses. No service or model connection is needed.

## Install and uninstall

Run from the repository root. Choose private capture and install directories.
The installer merges its registrations and keeps unrelated hooks and settings.
Close the agent before changing its configuration and restart it after setup.

```sh
python3 plugins/hooks-core/install.py firebender \
  --prefix "$HOME/.local/share/asr-hooks" \
  --config "$HOME/.firebender/hooks.json" \
  --output-dir "$HOME/.local/share/asr-captures"
```

Metadata capture is the default. Add `--content full` to retain available text,
input and output with known-secret exclusion. Keep captures private. The content
policy stays fixed for the lifetime of the captured session.

```sh
python3 plugins/hooks-core/install.py firebender \
  --prefix "$HOME/.local/share/asr-hooks" \
  --config "$HOME/.firebender/hooks.json" --uninstall
```

Uninstall removes only this install prefix's registrations and keeps captures.
Remove installed files after disabling all agents that share the prefix.

## Mapping and limits

This adapter targets Firebender's version 1 JSON hook configuration and the
payloads in its hook reference. Registrations are direct command entries in
the top-level `hooks` event map. Generic preToolUse and postToolUse preserve
native tool_use_id. PostToolUse is documented to follow successful execution.
Its duration is milliseconds and its input records effective arguments.
Tool output stays in metadata because later hooks can replace MCP output.

The installer omits beforeMCPExecution and beforeReadFile. Those events fail
closed on process errors, timeouts or invalid output, so a best-effort passive
recorder cannot safely attach to them. Generic preToolUse still observes their
tool requests. Other shell, MCP and edit callbacks remain observations rather
than duplicate tool calls or results. They cannot create guessed pairs.

SessionStart means a conversation became active. It does not establish that
the session is new, so initial time and cwd stay unknown. SessionEnd explicitly
sets a receipt-based end time. Subagent lifecycle uses the native agent_id for
separate streams without guessing immediate parent lineage. Stop and child
stop never set endedAt. Composer mode is recorded when supplied. User email,
transcript paths and workspace lists are omitted.

The fixed tool-name to ASR kind mapping is in [adapter.json](adapter.json).
Unlisted tool names keep their native spelling without a guessed kind.
The complete common loss list is `LOSSES` in the shared core's `projection.py`.
Adapter-specific losses are in adapter.json. Missing session IDs are never
invented. Hooks read no transcript or global agent configuration. Full-content capture
can observe Git metadata at an explicit new session start.

## Evidence and checks

Supported payload contract: the official documentation checked on 2026-11-01.
No binary compatibility beyond that documented contract is claimed.

- [Firebender hooks](https://docs.firebender.com/multi-agent/hooks)

[fixtures/hooks.json](fixtures/hooks.json) contains synthetic native payloads.
These are authored examples from the documented fields. They contain no real
session data. The shared suite checks mappings and native install round trips
and validates every generated ASR stream:

```sh
bash plugins/hooks-core/check.sh
```

Live status: **not live-tested**. This agent needs its own account. No account
was created or used. Synthetic tests establish payload handling only.
