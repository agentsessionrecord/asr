# Tabnine CLI ASR recorder

This recorder writes one append-only ASR 0.1 file per observed native session.
Python 3.11 or later and a POSIX host are required. The shared
[JSON hook core](../hooks-core/README.md) describes privacy, bounded storage,
receipt order and known losses. No service or model connection is needed.

## Install and uninstall

Run from the repository root. Choose private capture and install directories.
The installer merges its registrations and keeps unrelated hooks and settings.
Close the agent before changing its configuration and restart it after setup.

```sh
python3 plugins/hooks-core/install.py tabnine \
  --prefix "$HOME/.local/share/asr-hooks" \
  --config "$HOME/.tabnine/agent/settings.json" \
  --output-dir "$HOME/.local/share/asr-captures"
```

Metadata capture is the default. Add `--content full` to retain available text,
input and output with known-secret exclusion. Keep captures private. The content
policy stays fixed for the lifetime of the captured session.

```sh
python3 plugins/hooks-core/install.py tabnine \
  --prefix "$HOME/.local/share/asr-hooks" \
  --config "$HOME/.tabnine/agent/settings.json" --uninstall
```

Uninstall removes only this install prefix's registrations and keeps captures.
Remove installed files after disabling all agents that share the prefix.

## Mapping and limits

This adapter targets the Tabnine CLI 6.6 maintenance documentation. Tabnine
CLI is scheduled to be deprecated after 2026-12-31. This recorder does not target
the separate Tabnine Plugin for OpenCode. The installer uses the top-level
`hooks` event map with timeout values in milliseconds.

BeforeAgent records the submitted prompt. AfterAgent records prompt_response
as available assistant text. BeforeTool records the proposed arguments.
AfterTool's tool_input is explicitly the original request and stays in metadata.
It is never promoted to effective input. The documented payload has no call ID,
so requests get derived IDs and results stay unpaired.

AfterTool's llmContent supplies model-facing content when it is a string or an
array containing only text parts. returnDisplay is not recorded as model output.
Other media and provider-specific forms are omitted. A nonempty explicit error
string establishes failure. Otherwise result status stays unknown. Other hooks
can replace the output after this observation, which remains a declared loss.
Secret interaction tool content is excluded. Model-hook callbacks are retained
as observations without their raw requests or response chunks. The adapter does
not synthesize completed inference records from streaming chunks.

Startup and clear can establish a start receipt. Resume keeps the same native
identity and leaves an unobserved original start unknown. SessionEnd is best
effort and the CLI does not wait for it. Notification can observe a permission
request but does not reveal its answer. PreCompress does not claim that the
recorder's existing history was lost.

The fixed tool-name to ASR kind mapping is in [adapter.json](adapter.json).
Unlisted tool names keep their native spelling without a guessed kind.
The complete common loss list is `LOSSES` in the shared core's `projection.py`.
Adapter-specific losses are in adapter.json. Missing session IDs are never
invented. Hooks read no transcript or global agent configuration. Full-content capture
can observe Git metadata at an explicit new session start.

## Evidence and checks

Supported payload contract: the official documentation checked on 2026-11-01.
No binary compatibility beyond that documented contract is claimed.

- [Hooks](https://docs.tabnine.com/main/getting-started/tabnine-cli/features/hooks)
- [Events](https://docs.tabnine.com/main/getting-started/tabnine-cli/features/hooks/event-reference)

[fixtures/hooks.json](fixtures/hooks.json) contains synthetic native payloads.
These are authored examples from the documented fields. They contain no real
session data. The shared suite checks mappings and native install round trips
and validates every generated ASR stream:

```sh
bash plugins/hooks-core/check.sh
```

Live status: **not live-tested**. This agent needs its own account. No account
was created or used. Synthetic tests establish payload handling only.
