# Goose hook recorder

## Install

Build with `AGENT` set to `goose`. Copy the build directory to
`~/.agents/plugins/asr-recorder`, or a project `.agents/plugins/asr-recorder`.
Restart Goose with the storage variables set in its environment.
The plugin uses the normal Open Plugins `hooks/hooks.json` discovery.
For a source checkout installation, `node plugins/goose/configure.mjs` prints
a hooks file with absolute command paths. Copy it into the installed plugin.

## Uninstall

Remove the installed `asr-recorder` directory and restart Goose.
Existing ASR files remain in your output directory.

## Mapping

Tool IDs use `tool_call_id`. Initial arguments stay in metadata.
Post-tool arguments populate `tool_result.input`.
Goose supplies no tool output in these hooks. It is declared missing.
`PreToolUseResult` records an explicit denial or a clean evaluated allow.
An allow qualified by hook failure stays observational. A failure denial
uses `by: fallback`. Permission choices outside this chain stay missing.
`SessionStart` and `SessionEnd` are lifecycle observations. A turn `Stop`
does not end the session.

The contract comes from Goose `documentation/docs/guides/context-engineering/hooks.md`,
`crates/goose/src/hooks/mod.rs` and
`crates/goose/src/agents/state_machine/ops_toolcalling.rs`.

## Build and storage

From the repository root, run these commands. Use an empty output directory.

```sh
pnpm install --frozen-lockfile
pnpm --filter @agent-session/types build
pnpm --filter @agent-session/writer build
node plugins/remaining-core/build.mjs goose /tmp/asr-goose
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
