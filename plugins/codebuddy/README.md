# CodeBuddy ASR recorder

This passive recorder writes one append-only ASR file per native session. It
uses the hook contract checked on 2026-11-01. Python 3.11 or later and a POSIX host are required.
The shared [JSON hook core](../hooks-core/README.md) documents capture policy,
limits, storage and the adapter pattern.

## Install and uninstall

Run from the repository root. Choose private capture and install directories.
The installer merges its registrations into the selected native configuration.
It keeps other hooks and settings. Restart the agent after setup.

```sh
python3 plugins/hooks-core/install.py codebuddy \
  --prefix "$HOME/.local/share/asr-hooks" \
  --config "$HOME/.codebuddy/settings.json" \
  --output-dir "$HOME/.local/share/asr-captures"
```

Metadata is the default. Add `--content full` to retain available prompt,
reply, input and output text with known-secret exclusion. Keep the output
private. Read the shared core's capture policy before enabling full content.

```sh
python3 plugins/hooks-core/install.py codebuddy \
  --prefix "$HOME/.local/share/asr-hooks" \
  --config "$HOME/.codebuddy/settings.json" --uninstall
```

Uninstall removes this prefix's registrations and retains capture files. Remove
the installed files only after disabling all agents that use the shared prefix.

## Mapping and limits

This adapter uses the documented Claude-style event names and fields.
`generation_id` identifies a turn when supplied. The documented tool payloads
lack call IDs, so requests receive derived IDs and results stay unpaired.
Structured post-tool output stays in metadata. It is not relabeled as final
model-facing text. PermissionRequest is only a request. Explicit PermissionDenied
callbacks can supply a denial without a guessed decider or scope.

## Evidence and checks

Official [hook reference](https://www.codebuddy.cn/docs/cli/hooks), checked 2026-11-01.
Synthetic payloads are in [fixtures/hooks.json](fixtures/hooks.json). These are
authored protocol examples and contain no real sessions. Fields not supplied by
the documented contract remain unknown. The shared suite tests this adapter and
validates every generated ASR stream:

```sh
bash plugins/hooks-core/check.sh
```

Live status: **not live-tested**. This agent needs its own account. No account
was created or used. Synthetic fixtures establish payload handling only.
