# Gemini CLI recorder

Live-test status: **partial**. The current recorder passes offline regression
checks. A live run of this revision is pending.

This extension writes ASR 0.1 from Gemini CLI hooks to a local directory.
It observes BeforeTool, AfterTool, BeforeAgent, AfterAgent, SessionStart,
SessionEnd, Notification and PreCompress. It returns no decisions.

Live installation, tool execution, input rewriting, a blocked request and
uninstallation passed with Gemini CLI 0.66.0 through a local Gemini-compatible
endpoint. The recorder preserved the blocked request without guessing its outcome.

## Install

Use Node 22.13 or newer and pnpm. From the ASR repository root, run:

```sh
pnpm install --frozen-lockfile
pnpm --dir plugins/gemini-qwen-core build
gemini extensions install ./plugins/gemini-cli
```

The build creates a standalone recorder inside this extension. Installation
copies that file with the manifest and hooks. The installed extension does
not need the repository or pnpm. For local development, use
`gemini extensions link ./plugins/gemini-cli` after building.

Set the output directory and content policy when installing the extension or
with `gemini extensions config asr-gemini-cli`. These settings use the variables
ASR_OUTPUT_DIR and ASR_CONTENT. Set ASR_OUTPUT_DIR to an absolute directory
owned by you with mode 0700. Without it, recording stays off.

The default content policy keeps metadata. Set ASR_CONTENT to `full` to retain
available prompts, replies, arguments and tool output. Secret fields, known
credential patterns, credentials supplied in the hook environment, opaque
signatures and media bytes are excluded in either policy. Full capture can
still contain private material.

Restart Gemini CLI after installing. To uninstall, run:

```sh
gemini extensions uninstall asr-gemini-cli
```

Uninstalling leaves recordings in your selected directory. Delete them there
when you have finished using them.

## Mapping and limits

The mapping follows Gemini CLI 0.67.0 nightly source at commit
`a60946692b11e2f144a8fe4db46bbc4e514daa7a`. The source reference is
[hooks/reference.md](https://github.com/google-gemini/gemini-cli/blob/a60946692b11e2f144a8fe4db46bbc4e514daa7a/docs/hooks/reference.md).
The source files `packages/core/src/hooks/types.ts` and
`packages/core/src/core/coreToolHookTriggers.ts` establish the payload fields
and the arguments supplied after execution.

Gemini hooks supply no tool call ID. BeforeTool stays an observation of a
request under the declared extension `org.agentsessionrecord.hooks/v1`.
AfterTool produces a call and result at that receipt position with a derived
call ID. The recorder does not pair earlier requests by name, arguments or
timing. The call keeps the arguments supplied to AfterTool. The result keeps
llmContent rather than returnDisplay. Google parts without a plain text shape
remain typed vendor content parts. A supplied error makes the result failed.
An AfterTool response with no error makes it completed. Missing responses
leave status unknown. No exit code is guessed from text.

Hooks cannot observe other hooks' decisions or their final result rewrites.
Permissions and blocked calls may have no AfterTool event. These losses are
declared. BeforeModel and streaming AfterModel hooks are not registered.
The recorder does not claim complete model calls, usage, offered tools,
instructions, file changes, commits, settings, copy detection or child lineage.

Receipt times populate ts. An explicit SessionStart can establish startedAt.
An explicit SessionEnd establishes endedAt. AfterAgent never ends the session.
Resuming a native ID appends to the same stream. Current cwd on resume is not
reported as the starting cwd. Unknown prompt authorship stays unknown.

See the [shared core](../gemini-qwen-core/README.md) for storage and failure
limits. The [synthetic sample](samples/synthetic.jsonl) comes from the
[native hook fixture](../gemini-qwen-core/test/fixtures/gemini-cli.jsonl).
