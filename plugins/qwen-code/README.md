# Qwen Code recorder

Live-test status: **partial**. The current recorder passes offline regression
checks. A live run of this revision is pending.

This extension writes ASR 0.1 from Qwen Code command hooks. It observes tool
requests, permission requests, explicit automatic denials, tool outcomes,
final batches, prompts, final displayed replies and lifecycle callbacks.
It returns no decisions.

Live installation, tool execution, input rewriting, a refused request and
uninstallation passed with Qwen Code 0.26.5 through a local OpenAI-compatible
endpoint. Automatic classifier denial is covered by synthetic hook fixtures.

## Install

Use Node 22.13 or newer and pnpm. From the ASR repository root, run:

```sh
pnpm install --frozen-lockfile
pnpm --dir plugins/gemini-qwen-core build
qwen extensions install ./plugins/qwen-code
```

The build bundles the shared recorder and writer into this extension.
The installed copy needs Node but does not need the repository or pnpm.
For local development, use `qwen extensions link ./plugins/qwen-code`.

Choose an absolute output directory owned by you with mode 0700 and set
ASR_OUTPUT_DIR in the environment used to launch Qwen Code. Recording stays
off when that variable is absent. The default policy keeps metadata.
Set ASR_CONTENT to `full` to retain available text and structured arguments.

Secret fields, known credential patterns, credentials supplied in the hook
environment, opaque signatures and media bytes are excluded. Full capture can
still contain private material. Each stream declares known capture losses.

Restart Qwen Code after installation. To uninstall, run:

```sh
qwen extensions uninstall asr-qwen-code
```

Your recordings remain in the output directory until you delete them.

## Mapping and limits

The mapping follows Qwen Code 0.26.4 source at commit
`9ebd2de1713039b8cb5f60c9982e3d4c450e3a8b`. The official
[documentation](https://github.com/QwenLM/qwen-code/tree/9ebd2de1713039b8cb5f60c9982e3d4c450e3a8b/docs)
and `packages/core/src/hooks/types.ts` define the inputs.
`packages/core/src/core/coreToolScheduler.ts` defines batch serialization.
The extension uses the documented CLAUDE_PLUGIN_ROOT substitution for hook
commands. Command timeouts use seconds.

PreToolUse writes a call using tool_call_id when supplied, otherwise tool_use_id.
Explicit co-occurrence links the two native IDs across per-tool and batch hooks.
Its request input stays in vendor
metadata because another hook may rewrite it. PostToolUse and failure hooks
buffer effective input, outcome and duration. PostToolBatch completes one
result per ID at the batch receipt position. The result supplies the late
effective input under ASR-076. Batch request arguments remain in metadata
because they can disagree with the effective input.

Model-facing response_parts supply the result content. Display output from the
earlier callback stays in metadata. Google parts without a plain text shape
remain typed vendor content parts. Stop, StopFailure and SessionEnd flush
pending outcomes when a final batch is absent. That fallback declares missing
batch output and does not relabel display text as final content. Later batches
cannot replace an already completed result.

PermissionRequest records a request. It supplies no person's choice and no
call ID. The recorder does not turn it into an approval or guess a matching
call. PermissionDenied supplies an explicit denied decision. Only the reason
classifier_blocked establishes classifier as the decider. No lifetime is
guessed. Successful tools, modes and batch errors do not imply approvals.
The passive hook cannot observe other hooks' decisions or reviewer outputs.

Permission mode updates are preserved verbatim as approval policy. No asks
value or sandbox is inferred. MessageDisplay uses its final cumulative text
once per message ID. Stop does not duplicate it or end the session.
PostCompact records the supplied summary. Model context compaction alone does
not establish that this recorder lost earlier events.

Subagent callbacks stay in the containing session with their supplied agent ID
in vendor metadata. The recorder does not guess a child session ID or parent.
Usage, models, offered tools, complete instructions, edits, commits and copies
are declared missing. Receipt times and explicit session lifecycle events
follow ASR-009. Resume appends under the same native session ID.

See the [shared core](../gemini-qwen-core/README.md) for storage and failure
limits. The [synthetic sample](samples/synthetic.jsonl) comes from the
[native hook fixture](../gemini-qwen-core/test/fixtures/qwen-code.jsonl).
