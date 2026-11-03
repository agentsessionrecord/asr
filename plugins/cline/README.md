# Cline hook and live audit recorder

Live-test status: **partial**. The current recorder passes offline regression
checks. A live run of this revision is pending.

## Install

Build with `AGENT` set to `cline`. Copy the build's `hooks` directory into
an otherwise empty project `.cline/hooks` or `.clinerules/hooks` directory.
The executable filenames are Cline's normal file hook names.
Keep the bundle at its original absolute path after copying the hooks.
The copied scripts point back to that bundle.
Merge with existing hooks by calling the recorder from your existing scripts.
Do not replace a policy hook. Keep its return value and exit status.

Some hosts supply runtime hooks and omit the default `hooks.jsonl` audit.
If your host writes that audit, start this follower before the agent runs:

```sh
node /tmp/asr-cline/tail-audit.mjs /absolute/path/to/hooks.jsonl
```

The input file must already exist. The follower starts at EOF and records
only new complete lines. A partial line already present at startup is skipped.
Choose either file hooks or the follower for each
session. Running both duplicates observations.

## Uninstall

Remove the recorder hook files, or stop the audit follower by its PID.
Existing ASR files remain in your output directory.

## Mapping

The SDK payload uses `taskId` as native conversation identity.
`tool_call.id` and `tool_result.id` join the pair. The latter supplies
execution arguments, error, output and duration. A recorded error string
establishes failure. Without an error the outcome stays unknown because the
payload supplies no explicit success flag. An `agent_start` or
`agent_end` is a run boundary and does not set session lifetime.
`session_shutdown` is retained as an observation because it can mean reload.
The audit follower stops on truncation or malformed input. It never reads
historical audit records as live observations.
Hook control responses and final permission choices are unavailable here.

The contract comes from Cline
`sdk/packages/core/src/hooks/hook-file-hooks.ts`, `hook-file-config.ts`
and `apps/cli/src/utils/hooks.ts`.
The SDK local host runs file hooks when its `configExtensions` includes
`hooks`. An embedding host with its own hook execution layer can exclude
that extension. The VS Code host uses its own hook adapter.
CLI yolo mode omits its runtime callback bridge. That mode is not covered
by the live recording claim.

For an SDK embedding, enable file hooks when starting the session:

```js
const core = await ClineCore.create({ backendMode: 'local' });
try {
  await core.start({
    config: {
      providerId: 'openai-compatible',
      modelId: 'your-model',
      cwd: '/work/project',
      systemPrompt: 'Complete the requested task.',
      enableTools: true,
      enableSpawnAgent: false,
      enableAgentTeams: false,
    },
    prompt: 'Run the requested task.',
    interactive: false,
    localRuntime: { configExtensions: ['hooks'] },
  });
} finally {
  await core.dispose();
}
```

Import `ClineCore` from `@cline/core`. Configure the provider in the private
settings file used by `ProviderSettingsManager`. Use the provider identifier
`openai-compatible` for a compatible endpoint. Check its saved base URL
before making a request. The native CLI's `openai` alias did not use the
saved compatible-provider route in the tested configuration.

Some run boundary hooks are detached. Allow the host to finish them before
shutting down. The recorder emits a gap on observed lock contention.
An SDK start did not supply a prompt-submit callback in the tested path.

## Build and storage

From the repository root, run these commands. Use an empty output directory.

```sh
pnpm install --frozen-lockfile
pnpm --filter @agent-session/types build
pnpm --filter @agent-session/writer build
node plugins/remaining-core/build.mjs cline /tmp/asr-cline
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

Cline CLI 3.0.74 and SDK 0.2.0 each completed synthetic compatible endpoint tasks
with file hooks. Both hosts recorded one paired tool call and result per run.
Successful captures have 7 or 8 records. The 8-record captures also contain
agent_end. Detached final hooks were absent from some captures.
Validation found zero errors. For the CLI, select `-P openai-compatible`
and use normal act mode with the copied project hooks.
The VS Code host and CLI yolo mode are not live-tested.
See `live-test.json` for counts and validator warning codes.
