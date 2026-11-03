# Pi extension recorder

## Install

Build with `AGENT` set to `pi`. Load the extension for one invocation:

```sh
ASR_OUTPUT_DIR=/tmp/asr-output pi -e /tmp/asr-pi/index.mjs
```

For a persistent installation, run `pi install /tmp/asr-pi`.
The package declares its extension in `package.json`.

## Uninstall

Omit `-e`, or run `pi remove /tmp/asr-pi` for an installed package.
Existing ASR files remain in your output directory.

## Mapping

The native session identity comes from `sessionManager.getSessionId()`.
`tool_call` records a request without treating mutable pre-hook arguments
as effective input. `tool_result` supplies execution arguments.
`tool_execution_end` supplies the finalized model-facing result after
result rewrites. Only this final event emits a core result.
A blocked call may report only `isError`. It remains failed without an
invented denied approval. Approval and hook outcome coverage stay missing.
Reload and runtime shutdown observations do not set session end time.
Messages retain their role without guessing human authorship.
Reasoning and media content are omitted and declared missing.

The contract comes from Pi `packages/coding-agent/docs/extensions.md`,
`src/core/extensions/types.ts` and `src/core/agent-session.ts` in that package.

## Build and storage

From the repository root, run these commands. Use an empty output directory.

```sh
pnpm install --frozen-lockfile
pnpm --filter @agent-session/types build
pnpm --filter @agent-session/writer build
node plugins/remaining-core/build.mjs pi /tmp/asr-pi
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
