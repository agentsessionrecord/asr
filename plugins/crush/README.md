# Crush hook recorder

## Install

Build with `AGENT` set to `crush`. Merge the build's `hooks.json` object into
your `crush.json` configuration. Keep the build at its configured absolute
path. Restart Crush with the storage variables set in its environment.
For a source checkout, `node plugins/crush/configure.mjs` prints the object.

## Uninstall

Remove the entries named `asr-recorder` from your hook configuration.
Restart Crush. Existing ASR files remain in your output directory.

## Mapping

`tool_use_id` joins the calls. Post-tool arguments populate the result.
`PermissionRequest` records a request without a decision.
`PermissionResult` maps `granted`, `denied` and `cancelled` verbatim in meaning.
The callback does not establish whether a grant was remembered or freshly
answered, so no decider or grant scope is invented.
Subagents do not execute all of these wrappers. Their history stays missing.
A later hook can rewrite output. Final-output coverage stays incomplete.
Turn end does not set session end time.

The contract comes from Crush `internal/hooks/events.go`, `input.go`,
`runner.go`, `internal/agent/hooked_tool.go` and `internal/app/hooks.go`.

## Build and storage

From the repository root, run these commands. Use an empty output directory.

```sh
pnpm install --frozen-lockfile
pnpm --filter @agent-session/types build
pnpm --filter @agent-session/writer build
node plugins/remaining-core/build.mjs crush /tmp/asr-crush
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

Live-test status: **partial**.
The current recorder passes offline regression checks. A live run of this
revision is pending.
