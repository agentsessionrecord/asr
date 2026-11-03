# Codex hook recorder

Record Codex command hooks as Agent Session Record 0.1. Each session has one
private, append-only JSONL file. Tested with Codex CLI 0.163.0 on Linux.
Python 3.11 or later and a POSIX filesystem are required.

## Install

From this repository, install the workspace packages:

```sh
uv sync --all-packages
```

Generate a hook configuration with the installed interpreter:

```sh
.venv/bin/python -m asr_codex_hooks config --output /private/asr > hooks.generated.json
```

Use a private output directory owned by your user. The recorder creates it
with mode `0700` when it does not exist. Files use mode `0600`.

Copy `hooks.generated.json` to `$CODEX_HOME/hooks.json`. The usual Codex home
is `~/.codex`. If you already have hooks, merge the generated event groups into
the existing `hooks` object. Keep all existing groups. You can instead use a
trusted project's `.codex/hooks.json`.

Open `/hooks` in Codex and review and trust each recorder hook. Enable the
`hooks` feature if your Codex build requires it. For reviewed, disposable
automation, Codex also supports `--dangerously-bypass-hook-trust`.

The generated command contains the absolute Python and output paths. Keep the
installation at that location. Hooks use a one-second Codex timeout and stay
silent. They never return approval, rejection, rewrite or continuation output.
They run synchronously to preserve receipt order and finish quickly. Capture
has a 750 ms deadline after stdin, and stdin has a 100 ms deadline. A lock
wait lasts at most 100 ms. Capture errors return exit code zero.

## Content and privacy

The default captures event names, native IDs, permission labels, active model
labels and tool names. It omits prompts, commands, responses and paths.
To retain available content, generate the configuration with `--full`:

```sh
.venv/bin/python -m asr_codex_hooks config --full --output /private/asr
```

Both modes exclude named credential fields, common credential patterns and
credential values present in environment variables with sensitive names.
Redacted records declare the loss and mark shortened text. Opaque signatures
and encrypted reasoning state are excluded. Review output before sharing it.
The recorder never reads the transcript, Git configuration or account files.

## What is captured

All 14 hook events in the inspected Codex source are registered. These include
pre and post model requests, pre and post tool use, permission requests,
compaction, prompts, session and subagent starts, stop events and interrupts.
Each callback has a receipt timestamp and a declared
`org.agentsessionrecord.hooks/hook` extension record. Available token usage stays
in that observation. It is not promoted to session totals or linked to guessed
inferences.

| Source observation | ASR mapping |
| --- | --- |
| Fresh `SessionStart` or `SubagentStart` | Header `startedAt` from receipt time |
| Resume, fork or compaction start | Same native identity without an invented creation time |
| `SessionEnd` | `session_info.endedAt` from receipt time |
| `Stop`, `SubagentStop`, `Interrupt` | Observation only, without a session end |
| `permission_mode` changes | Verbatim `agentSettings.approval` compatibility label |
| `UserPromptSubmit` | User message in full mode, without guessed human authorship |
| `PreToolUse` | Call with native ID and exact tool name |
| Pre-tool input | `requestedInput` in namespaced metadata in full mode |
| `PostToolUse` | One result per call ID, at callback receipt |
| Post-tool input | Effective `tool_result.input` in full mode |
| Post-tool response | Text content or MCP parts in full mode |
| MCP `isError` boolean | Explicit completed or failed outcome |
| Shell response text | Unknown outcome, without parsing exit status from text |
| `PermissionRequest` | Request observation, without a decision or guessed call link |

`Bash` maps to execute and `apply_patch` maps to edit. Other tool kinds stay
unknown. Request authorship stays unknown. The pre-tool input is a request
that another hook may rewrite. Only post-tool input becomes effective input.
Post-tool output is the output observed before other post-tool hooks can
replace it. The final output after those hooks is unavailable.

Subagent callbacks use `agent_id` as the child identity and write a separate
file. The containing `session_id` does not establish the immediate parent.
No parent or spawning call is guessed. A child stop can continue the turn and
does not establish session end.

The compatibility permission label does not identify native approval or
sandbox policies. It does not establish `asks`. Active model labels do not
establish the model that served a request.

## Hook responses

Codex starts matching hooks concurrently. One hook cannot observe another
hook's stdout, exit status or final aggregate outcome through its stdin.
The recorder therefore declares hook outcomes and approvals incomplete.

You can observe a specific existing command hook by wrapping its command.
Keep its matcher and timeout. Replace only its command with:

```sh
/absolute/path/.venv/bin/python -m asr_codex_hooks wrap --full --output /private/asr -- python3 /absolute/path/policy.py
```

For a shell command, explicitly use `sh -c` after `--`. The wrapper forwards
stdin and both output streams, preserves output bytes and the command's exit
status, and records its response after completion. Each output stream has a
512 KiB observation limit. Forwarding continues beyond that limit. Recording
is best effort and never changes the forwarded decision or rewrite.

The response is a proposal from one hook. Codex can reject an invalid response,
another hook can deny, and a managed human checkpoint can still apply.
Wrapped responses stay in the extension with `responseIsProposal: true`.
They never become final `approval` records.

Guardian reviewer verdicts and human choices are absent from hook stdin.
They cannot be recovered by this recorder. Use an independent telemetry
capture when those decisions are required. Do not infer approval from a
successful command or refusal from a missing result.

## Storage limits and failures

The recorder uses the shared Python hook store and writer. A private sidecar
holds the append position, pairing index and settings. Only new records are
validated. Native session IDs are hashed for filenames. Large native integers
are preserved as strings. The producer is `asr-hooks-codex` and the declared
extension is `org.agentsessionrecord.hooks/v1`.

Input is limited to 1 MiB, streams to 16 MiB and sidecars to 512 KiB. A cap or
inconsistent sidecar writes a terminal gap and seals capture. Complete lines
are never rewritten. A torn final line stays untouched and a separate capture
of the same session declares the loss. Contention, oversized input and deadline
failures leave markers for a gap on a later callback. Disk failure or process
termination can prevent that notice. Symlink files and public output directories
are refused. Capture is local and best effort, without a completeness guarantee.

Every header declares known missing data, including native times, reasoning,
usage, final tool output, exit codes, file changes, commits, subagent links,
copies, served models, approvals, native policies, tools, instructions, costs,
user and message identity, triggers, assistant history, hook outcomes,
automatic reviewer verdicts, native record IDs and unmapped hook fields.
Metadata mode additionally declares content and paths missing.

## Test

```sh
uv run --all-packages pytest plugins/codex/tests
```

To rebuild the committed synthetic sample:

```sh
uv run --all-packages python plugins/codex/scripts/replay_fixture.py plugins/codex/fixtures/sample.jsonl
```

The tests use synthetic hook payloads, exercise all registered events and
validate their completed streams with the Node validator. The native fixture
and emitted ASR sample are in `fixtures/`. The source contract is Codex
0.163.0, source checkout at commit `4b4a5cf25a`, and the
[official hook documentation](https://developers.openai.com/codex/hooks).

Run the optional live test against an OpenAI-compatible endpoint. Supply an
explicit loopback URL, model and private credential file:

```sh
uv run --all-packages python plugins/codex/scripts/live_test.py /private/live-summary.json --base-url "$ASR_OPENAI_BASE_URL" --model "$ASR_OPENAI_MODEL" --key-file "$ASR_PROVIDER_KEY_FILE"
```

The test writes private provider settings in disposable home and config
directories and deletes them afterward. It checks an allowed command, a
permission-hook refusal and a pre-tool rewrite. Only aggregate counts and
assertion results are retained.

## Uninstall

Remove the generated recorder groups from your `hooks.json` and remove any
wrappers you added to existing hooks. Restart Codex. Delete the output
directory if you want to remove captures, then remove the local package
installation when finished.

## Test status

Live-test status: **partial**.
The current recorder passes offline regression checks. A live run of this
revision is pending.
