# Copilot CLI ASR recorder

This passive recorder writes one append-only ASR file per native session. It
uses the camelCase hook contract checked on 2026-11-01. Python 3.11 or later and a POSIX host are required.
The shared [JSON hook core](../hooks-core/README.md) documents capture policy,
limits, storage and the adapter pattern.

## Install and uninstall

Run from the repository root. Choose private capture and install directories.
The installer merges its registrations into the selected native configuration.
It keeps other hooks and settings. Restart the agent after setup.

```sh
python3 plugins/hooks-core/install.py copilot-cli \
  --prefix "$HOME/.local/share/asr-hooks" \
  --config "$PWD/.github/hooks/asr.json" \
  --output-dir "$HOME/.local/share/asr-captures"
```

Metadata is the default. Add `--content full` to retain available prompt,
reply, input and output text with known-secret exclusion. Keep the output
private. Read the shared core's capture policy before enabling full content.

```sh
python3 plugins/hooks-core/install.py copilot-cli \
  --prefix "$HOME/.local/share/asr-hooks" \
  --config "$PWD/.github/hooks/asr.json" --uninstall
```

Uninstall removes this prefix's registrations and retains capture files. Remove
the installed files only after disabling all agents that use the shared prefix.

## Mapping and limits

The installer uses native camelCase event names. The event is passed as a
command argument because most payloads omit it. Notification payloads use the
documented PascalCase event field and are normalized explicitly. Session IDs,
tool names, arguments and model-facing `textResultForLlm` map to core records.
PascalCase compatibility payloads are outside this adapter's supported contract.

The documented command payloads have no call IDs. Results remain unpaired even
when adjacent requests have the same name and input. Permission requests do not
state the eventual choice. Do not infer a grant from successful execution.
Command hooks may run within Copilot's sandbox. Its policy must allow access to
the install and output directories. This POSIX adapter does not install
PowerShell hooks.

## Evidence and checks

Official [hook reference](https://docs.github.com/en/copilot/reference/hooks-reference), checked 2026-11-01.
Synthetic payloads are in [fixtures/hooks.json](fixtures/hooks.json). These are
authored protocol examples and contain no real sessions. Fields not supplied by
the documented contract remain unknown. The shared suite tests this adapter and
validates every generated ASR stream:

```sh
bash plugins/hooks-core/check.sh
```

Live status: **not live-tested**. This agent needs its own account. No account
was created or used. Synthetic fixtures establish payload handling only.
