# Cursor ASR recorder

This passive recorder writes one append-only ASR file per native session. It
uses the hook contract checked on 2026-11-01. Python 3.11 or later and a POSIX host are required.
The shared [JSON hook core](../hooks-core/README.md) documents capture policy,
limits, storage and the adapter pattern.

## Install and uninstall

Run from the repository root. Choose private capture and install directories.
The installer merges its registrations into the selected native configuration.
It keeps other hooks and settings. Restart the agent after setup.

```sh
python3 plugins/hooks-core/install.py cursor \
  --prefix "$HOME/.local/share/asr-hooks" \
  --config "$HOME/.cursor/hooks.json" \
  --output-dir "$HOME/.local/share/asr-captures"
```

Metadata is the default. Add `--content full` to retain available prompt,
reply, input and output text with known-secret exclusion. Keep the output
private. Read the shared core's capture policy before enabling full content.

```sh
python3 plugins/hooks-core/install.py cursor \
  --prefix "$HOME/.local/share/asr-hooks" \
  --config "$HOME/.cursor/hooks.json" --uninstall
```

Uninstall removes this prefix's registrations and retains capture files. Remove
the installed files only after disabling all agents that use the shared prefix.

## Mapping and limits

The conversation ID is the session ID. Generation IDs identify turns.
The start callback does not distinguish a new conversation from a resume.
Capture leaves the original start time and working directory unknown and
marks earlier history as missing. Generic
pre-tool and post-tool events avoid duplicate shell-specific observations.
`tool_output` is a JSON-stringified structured payload. It stays in metadata
because the hook contract does not promise final model-facing content.
`failure_type: permission_denied` states a denied result, not an approval.

Permission and prompt callbacks deliberately exit `1` with `failClosed: false`.
Cursor documents that this path permits the action without a decision. Empty
output on a successful permission hook can block it. Hook error logs can show
this passive exit. This behavior needs a live account test before deployment.
Subagent start describes an attempted spawn. Its instance ID is kept in metadata
without claiming a new child session or immediate parent.

## Evidence and checks

Official [hook reference](https://cursor.com/docs/hooks), checked 2026-11-01.
Synthetic payloads are in [fixtures/hooks.json](fixtures/hooks.json). These are
authored protocol examples and contain no real sessions. Fields not supplied by
the documented contract remain unknown. The shared suite tests this adapter and
validates every generated ASR stream:

```sh
bash plugins/hooks-core/check.sh
```

Live status: **not live-tested**. This agent needs its own account. No account
was created or used. Synthetic fixtures establish payload handling only.
