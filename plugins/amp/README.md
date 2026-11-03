# Amp plugin recorder

## Install

Build with `AGENT` set to `amp`. Copy `index.mjs` from the build to
`.amp/plugins/asr-recorder.mjs` in your project. Reload plugins from Amp's
command palette. Set the storage variables in Amp's launching environment.
The bundled plugin imports no files from this checkout.

## Uninstall

Remove `.amp/plugins/asr-recorder.mjs` and reload plugins.
Existing ASR files remain in your output directory.

## Mapping

`event.thread.id` is the native identity. `toolUseID` joins calls.
`tool.call` returns the API's neutral `{ action: allow }` response.
`tool.result` supplies execution input, status and available output.
Callbacks are not ordered after every other plugin, so final rewrite and
permission decision coverage stay missing. `agent.end` ends a turn rather
than the thread. `session.start` may open an existing thread and does not
establish its original start time. No session end is invented.
No account identity is collected.

The contract is the official [Amp plugin API](https://ampcode.com/docs/plugin-api),
checked on the date in `sources.json`. An Amp account was not used.

## Build and storage

From the repository root, run these commands. Use an empty output directory.

```sh
pnpm install --frozen-lockfile
pnpm --filter @agent-session/types build
pnpm --filter @agent-session/writer build
node plugins/remaining-core/build.mjs amp /tmp/asr-amp
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
Official plugin API fixtures and the standalone bundle pass. An Amp account was not used.
