# Auggie CLI ASR recorder

This recorder writes one append-only ASR 0.1 file per observed native session.
Python 3.11 or later and a POSIX host are required. The shared
[JSON hook core](../hooks-core/README.md) describes privacy, bounded storage,
receipt order and known losses. No service or model connection is needed.

## Install and uninstall

Run from the repository root. Choose private capture and install directories.
The installer merges its registrations and keeps unrelated hooks and settings.
Close the agent before changing its configuration and restart it after setup.

```sh
python3 plugins/hooks-core/install.py auggie \
  --prefix "$HOME/.local/share/asr-hooks" \
  --config "$HOME/.augment/settings.json" \
  --output-dir "$HOME/.local/share/asr-captures"
```

Metadata capture is the default. Add `--content full` to retain available text,
input and output with known-secret exclusion. Keep captures private. The content
policy stays fixed for the lifetime of the captured session.

```sh
python3 plugins/hooks-core/install.py auggie \
  --prefix "$HOME/.local/share/asr-hooks" \
  --config "$HOME/.augment/settings.json" --uninstall
```

Uninstall removes only this install prefix's registrations and keeps captures.
Remove installed files after disabling all agents that share the prefix.

## Mapping and limits

This adapter targets Auggie's documented 1.x command-hook contract. It uses
the top-level `hooks` event map and timeout values in milliseconds. It does not
request optional user, MCP or conversation metadata. Both input and output
field names come from the hook reference.

conversation_id supplies the session identity. PromptSubmit uses user_prompt.
Tool hooks expose no documented call ID. Requests get derived IDs and results
stay unpaired. tool_is_error explicitly supplies success or failure. A nonempty
tool_error also supplies failure. Otherwise status remains unknown. Post-tool
arguments are effective input. Raw tool_result blocks, tool_output and reported
file_changes stay in metadata. No applied file-change normalization or final
model-facing serialization is claimed.

SessionStart is documented as a new-session event. Only SessionEnd sets an end
time. Stop is a turn boundary. Subagent tool callbacks may appear without an
independent child identity. They do not establish lineage or separate child
streams. Notification remains an observation, including permission alerts.
Other hooks' decisions and rewrites remain missing.

The fixed tool-name to ASR kind mapping is in [adapter.json](adapter.json).
Unlisted tool names keep their native spelling without a guessed kind.
The complete common loss list is `LOSSES` in the shared core's `projection.py`.
Adapter-specific losses are in adapter.json. Missing session IDs are never
invented. Hooks read no transcript or global agent configuration. Full-content capture
can observe Git metadata at an explicit new session start.

## Evidence and checks

Supported payload contract: the official documentation checked on 2026-11-01.
No binary compatibility beyond that documented contract is claimed.

- [Auggie hooks](https://docs.augmentcode.com/cli/hooks)

[fixtures/hooks.json](fixtures/hooks.json) contains synthetic native payloads.
These are authored examples from the documented fields. They contain no real
session data. The shared suite checks mappings and native install round trips
and validates every generated ASR stream:

```sh
bash plugins/hooks-core/check.sh
```

Live status: **not live-tested**. This agent needs its own account. No account
was created or used. Synthetic tests establish payload handling only.
