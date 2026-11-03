# Grok Build hook recorder

## Install

Build with `AGENT` set to `grok-build`. Copy the build's `hooks.json` into
`~/.grok/hooks/asr-recorder.json`. Restart Grok with the storage variables set.
For a source checkout, `node plugins/grok-build/configure.mjs` prints the file.
Managed policy can disable local hooks. The recorder does not bypass it.

## Uninstall

Remove `~/.grok/hooks/asr-recorder.json` and restart Grok.
Existing ASR files remain in your output directory.

## Mapping

The envelope mixes `hook_event_name` with camelCase data fields.
`sessionId`, `toolUseId`, `toolName`, `toolInput` and `toolResult` are mapped
explicitly. `permissionMode` stays verbatim. An explicit `PermissionDenied`
emits a denial without guessing the decider or scope.
Post-hook output can still be rewritten by another hook, so final-output
coverage is declared incomplete. `toolInputTruncated` is retained as evidence.
The recorder makes no live account claim.

The contract comes from Grok
`crates/codegen/xai-grok-pager/docs/user-guide/10-hooks.md` and
`crates/codegen/xai-grok-shell/src/session/acp_session_impl/tool_calls.rs`.

## Build and storage

From the repository root, run these commands. Use an empty output directory.

```sh
pnpm install --frozen-lockfile
pnpm --filter @agent-session/types build
pnpm --filter @agent-session/writer build
node plugins/remaining-core/build.mjs grok-build /tmp/asr-grok-build
```

The build contains its runtime dependencies. It needs Node 22.13 or later.
Build it at the path you will keep. Generated command configurations contain
that absolute path, except the portable Goose and Mux plugin configurations.
No package is published by this build.

Set `ASR_OUTPUT_DIR` to an absolute directory owned by you with mode `0700`.
The recorder creates it if absent. Files have mode `0600`.
Leave `ASR_CONTENT` unset to omit prompts, tool arguments and output.
Set `ASR_CONTENT=full` to retain available content after known secret exclusion.
Never put credentials in hook configuration. See the
[shared recorder](../remaining-core/README.md) for limits and loss declarations.

## Tests

Run `bash plugins/remaining-core/check.sh` from the repository root.
The synthetic native payloads are in `fixtures/native.jsonl`.
Supported source revisions are pinned in `sources.json`.

Live-test status: **not-live-tested**.
Source-shaped synthetic fixtures validate. No Grok account was used.
