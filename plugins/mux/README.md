# Mux and Xum MCP hook recorder

Live-test status: **partial**. The current recorder passes offline regression
checks. A live run of this revision is pending.

## Install

Build with `AGENT` set to `mux`. The output is a complete Codex-format plugin.
Install it through Xum's managed plugin mechanism in Settings, using a local
Git source containing the build directory. Review the MCP component and
all four hook definitions. Enable the `asr-recorder` MCP server for the
workspace and trust each recorder hook in Settings.
Set the storage variables in the environment that launches Xum.
The manifest forwards only `ASR_OUTPUT_DIR` and `ASR_CONTENT` to the MCP process.
The server starts disabled. Enabling the MCP component and trusting the hook
hashes are separate steps. Repeat the review after changing a hook.

The debug CLI can also perform the managed flow. Use
`xum api agent-plugins preview` on the local Git source, then install the
returned source, method, SHA and consent digest. Select the `asr-recorder`
MCP component. Review all four hooks with `agent-plugins get-hooks` and
`agent-plugins set-hook-trust`. Use `projects set-trust` for the local project.
Read the plugin's full server key with `mcp list`. Enable that key through
`workspace mcp get` and `workspace mcp set`, using the returned revision.
Read back each setting to confirm it took effect.

These hooks require a trusted local or worktree workspace. Project plugin
folders, side chats and remote workspaces do not run Codex-format hooks.
The JavaScript hook sandbox has no filesystem access. This plugin uses the
documented `mcp_tool` mechanism and writes through its local stdio server.

## Uninstall

Uninstall `asr-recorder` in Settings and disable its MCP server.
Existing ASR files remain in your output directory.

## Mapping

`session_id` is the workspace ID. `tool_use_id` joins calls.
The MCP observer always returns JSON `{}` and makes no permission decision.
Post-hook input is not promoted to effective input because later script
hooks can rewrite it and the payload does not establish final arguments.
Post-tool response is captured with unknown status because this interface
has no reliable outcome field. There are no session start or end callbacks.
The permission mode is recorded without deriving a person's answer.

The contract comes from Mux `docs/hooks/plugins.mdx`,
`src/node/services/agentPlugins` and `src/node/services/tools/withHooks.ts`.
Xum 0.32.1 completed this managed installation flow in a trusted local
workspace. All four callbacks ran during a synthetic compatible endpoint task.
The 14-record ASR stream contains the prompt, final assistant text and one
paired tool call and result. The result status remains unknown.
Validation found zero errors. A workspace creation attempt was refused
until project trust was granted.

The 0.32.1 debug CLI reported an output validation error for successful void
responses from hook trust and workspace MCP changes. Reading those settings
back confirmed that the changes were applied.
See `live-test.json` for counts and validator warning codes.

## Build and storage

From the repository root, run these commands. Use an empty output directory.

```sh
pnpm install --frozen-lockfile
pnpm --filter @agent-session/types build
pnpm --filter @agent-session/writer build
node plugins/remaining-core/build.mjs mux /tmp/asr-mux
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
