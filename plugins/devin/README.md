# Devin CLI ASR recorder

This recorder writes one append-only ASR 0.1 file per observed native session.
Python 3.11 or later and a POSIX host are required. The shared
[JSON hook core](../hooks-core/README.md) describes privacy, bounded storage,
receipt order and known losses. No service or model connection is needed.

## Install and uninstall

Run from the repository root. Choose private capture and install directories.
The installer merges its registrations and keeps unrelated hooks and settings.
Close the agent before changing its configuration and restart it after setup.

```sh
python3 plugins/hooks-core/install.py devin \
  --prefix "$HOME/.local/share/asr-hooks" \
  --config "$HOME/.config/devin/config.json" \
  --output-dir "$HOME/.local/share/asr-captures"
```

Metadata capture is the default. Add `--content full` to retain available text,
input and output with known-secret exclusion. Keep captures private. The content
policy stays fixed for the lifetime of the captured session.

```sh
python3 plugins/hooks-core/install.py devin \
  --prefix "$HOME/.local/share/asr-hooks" \
  --config "$HOME/.config/devin/config.json" --uninstall
```

Uninstall removes only this install prefix's registrations and keeps captures.
Remove installed files after disabling all agents that share the prefix.

## Mapping and limits

The supported contract is the documented Devin CLI JSON command-hook protocol.
The installer also accepts the unwrapped `.devin/hooks.v1.json` event map when
you select that filename. Other config files use the top-level `hooks` object.

The documented stdin has session and prompt IDs but no tool-call ID. Requests
get derived IDs and results stay unpaired. Post-tool `success` explicitly sets
completed or failed status. Missing success stays unknown. Post-tool arguments
are effective input. Output stays in metadata because another post hook can
rewrite it before the model sees it. PostCompaction preserves its summary as a
harness compaction message. It does not claim captured history was destroyed.

SessionStart is documented as a new-session event and can set receipt-based
start time. Only SessionEnd sets an end time. PermissionRequest is an observed
request and never an approval. Other hooks' choices and rewrites are missing.

The fixed tool-name to ASR kind mapping is in [adapter.json](adapter.json).
Unlisted tool names keep their native spelling without a guessed kind.
The complete common loss list is `LOSSES` in the shared core's `projection.py`.
Adapter-specific losses are in adapter.json. Missing session IDs are never
invented. Hooks read no transcript or global agent configuration. Full-content capture
can observe Git metadata at an explicit new session start.

## Evidence and checks

Supported payload contract: the official documentation checked on 2026-11-01.
No binary compatibility beyond that documented contract is claimed.

- [Hook overview](https://docs.devin.ai/cli/extensibility/hooks/overview)
- [Lifecycle events](https://docs.devin.ai/cli/extensibility/hooks/lifecycle-hooks)

[fixtures/hooks.json](fixtures/hooks.json) contains synthetic native payloads.
These are authored examples from the documented fields. They contain no real
session data. The shared suite checks mappings and native install round trips
and validates every generated ASR stream:

```sh
bash plugins/hooks-core/check.sh
```

Live status: **not live-tested**. This agent needs its own account. No account
was created or used. Synthetic tests establish payload handling only.
