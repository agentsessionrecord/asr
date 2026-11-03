# DeepSeek harness hook bridge recorder

Live-test status: **partial**. The current recorder passes offline regression
checks. A live run of this revision is pending.

## Install

Build with `AGENT` set to `deepseek-harness`. Save the build's `hooks.json`.
Install the official Claude command hook bridge in your selected profile.
This example uses the `headless` profile:

```sh
dsh plugin --profile headless add @deepseek-ai/dsh-hooks-claude-code@0.2.2-alpha.2
dsh plugin --profile headless add @deepseek-ai/dsh-hook-protocol@0.2.2-alpha.2
```

Add this insert to that profile's `cordis.patch.yml`:

```yaml
- insert:
    - id: asr-recorder
      name: '@deepseek-ai/dsh-hooks-claude-code'
      config:
        configPath: /tmp/asr-deepseek-harness/hooks.json
```

For a source checkout, `node plugins/deepseek-harness/configure.mjs` prints
that hook configuration. Keep the build at its configured absolute path.

## Uninstall

Remove that bridge entry if it serves only this recorder. Otherwise remove
only the recorder commands from its hooks file. Restart the harness.
Existing ASR files remain in your output directory.

## Mapping

The official bridge supplies Claude-shaped JSON on standard input.
`session_id` and `tool_use_id` are preserved. Post-tool input is execution
input. The bridge flattens text output and omits structured content.
It supplies no reliable result status, so the recorder uses unknown.
The bridge's own hook outcome ledger is not exposed to these hooks.
No `SessionEnd` exists in this bridge. `Stop` cannot establish one.
Subagent callbacks without native child session identity stay observational.

The contract comes from
`packages/experimental/hooks-claude-code/src/index.ts` and its README.
The inspected CLI needs Node 24.9 or later.
Version 0.2.2-alpha.2 recorded a live shell task through a OpenAI-compatible or Anthropic-compatible endpoint.

## Build and storage

From the repository root, run these commands. Use an empty output directory.

```sh
pnpm install --frozen-lockfile
pnpm --filter @agent-session/types build
pnpm --filter @agent-session/writer build
node plugins/remaining-core/build.mjs deepseek-harness /tmp/asr-deepseek-harness
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
