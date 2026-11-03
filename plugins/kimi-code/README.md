# Kimi Code command hook recorder

Live-test status: **partial**. The current recorder passes offline regression
checks. A live run of this revision is pending.

## Install

Build with `AGENT` set to `kimi-code`. For Kimi Code 2.x, merge the build's
`hooks-v2.toml` entries into `~/.kimi-code/config.toml`. For Python Kimi 1.52,
merge `hooks.toml` into that host's configuration file. Install only one list.
Each `[[hooks]]` entry uses the normal command hook mechanism.
Keep the build at its configured absolute path.
For a source checkout, `node plugins/kimi-code/configure.mjs --v2` prints
2.x entries. Omit `--v2` for the 1.52 contract.
Run `kimi doctor` to check that your configuration loads before starting work.

## Uninstall

Remove the recorder's `[[hooks]]` entries and restart Kimi.
Existing ASR files remain in your output directory.

## Mapping and supported version

This adapter supports the Python Kimi CLI 1.52.0 and Kimi Code 2.4.1
hook contracts. The 2.x configuration covers 20 public hook events.
`tool_call_id` joins calls. `tool_output` supplies post-tool text.
The pre-tool request stays in metadata. Post-tool arguments go on the result.
Failure hooks explicitly establish failed status and retain error message
and code. Successful output at the host's 2000 character limit is marked
truncated because the callback cannot distinguish an exact fit from clipping.

2.x prompt content parts retain text in order. Omitted media marks the message
truncated. Queued prompts and turn starts remain observations to avoid
repeating the submitted message. Stop does not expose assistant text in 2.x.
Subagent callbacks have no child session ID, so they remain observations
without invented lineage.

2.x PermissionResult records explicit approval, rejection and cancellation.
An explicit session grant keeps its scope. Errors and permission requests
produce no approval. No person or decider is inferred.

The 1.52 contract comes from `src/kimi_cli/hooks`. The 2.x contract comes
from `packages/agent-core-v2/src/features/externalHooks` and
`packages/agent-core-v2/src/agent/toolApproval`. Public sources are pinned
in `sources.json`.

## Build and storage

From the repository root, run these commands. Use an empty output directory.

```sh
pnpm install --frozen-lockfile
pnpm --filter @agent-session/types build
pnpm --filter @agent-session/writer build
node plugins/remaining-core/build.mjs kimi-code /tmp/asr-kimi-code
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
Synthetic native payloads and validator-checked ASR are in `fixtures`.
The 2.x fixtures cover all configured events, structured prompts, failures
and explicit permission outcomes. The legacy fixtures remain checked.

Kimi Code 2.4.1 completed a synthetic tool task through a OpenAI-compatible or Anthropic-compatible endpoint.
Its 10-record stream contains six callbacks and one paired tool call and
result. Validation found zero errors. SessionEnd was not observed on that
print-mode exit. Live permission outcomes and the 1.52 runtime are untested.
See `live-test.json` for counts and validator warning codes.
