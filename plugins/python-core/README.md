# Python hook recorder support

This package shares local storage and safety rules for the Python agent plugins.
Agent mappings live in their own plugin directories. It uses the Python ASR
writer. The writer can reopen a complete stream without changing earlier bytes.
File locking requires a POSIX Python environment.

Set `ASR_OUTPUT_DIR` to an absolute directory before starting the agent.
Without it, recording is disabled. Each native session gets one hashed filename.
The header keeps the native session ID. New files have mode `0600` and new
directories have mode `0700`.

The default capture keeps event names, tool names, outcomes and decisions.
Set `ASR_CONTENT=full` to include available prompts, replies, arguments and
output. Known credential fields, token patterns and secret values from the
process environment are excluded in both modes. Content can still contain
private work. Review files before sharing them.

Every stream declares the extension `org.agentsessionrecord.hooks/v1`.
Its `org.agentsessionrecord.hooks/hook` records preserve observed hook events
that have no core equivalent. Other source facts use the same reverse DNS key
in `_meta`. An unaware reader can ignore the extension. The validator warns
about its name and event records.

Pre-tool arguments go in `_meta` as `requestedInput`. They can still change.
Where a post-tool hook supplies effective arguments with a native call ID,
the result carries `input` under ASR-076. A request for permission does not
establish a decision. A tool's exit code does not establish its lifecycle status.
Turn completion does not establish session end.

The header declares known losses for reasoning, usage, native timestamps,
tool output, exit codes, file changes, commits, subagents, copies, models,
approvals, agent settings, offered tools, instructions, session users,
message people, message authorship, triggers, hook decisions, input rewrites,
bounded capture and native record IDs. These names describe incomplete
coverage. Captured facts remain useful. Individual plugins add narrower losses.
Cost, message history, media, complete session lifecycle, parent lineage and
final model-facing output are also incomplete.
Metadata capture also declares content and paths. Redaction or shortening adds
`redacted` and sets `truncated` on the affected record.
An unsafe native session ID disables capture for that session. An observation
with an unsafe call or turn ID becomes a gap. IDs are never shortened or
redacted into a different identity.

Hermes and AstrBot snapshot selected payload fields into a queue with 256 slots.
A daemon thread writes them in receipt order. Queue overflow is reported by a
gap at the next retained observation. Agent shutdown can lose queued callbacks.
Callbacks never wait for a flush. A process that embeds these plugins can call
the observer's `flush()` during its own explicit shutdown handling.

Command hooks finish a local append before returning. A 750 ms deadline covers
input, schema imports, lock acquisition and writes. They print nothing and
return success when parsing, imports or storage fail. A lock waits at most
100 ms. Lost callbacks leave a marker for a gap on the next successful write.
Separate sessions use separate locks.

A private sidecar keeps the stream size, file identity, position, record IDs,
completed call IDs and adapter state. Only new records are validated. A stale
or malformed sidecar seals the stream with a gap. A torn final line stays
untouched, with the stop recorded in a separate capture of the same session.
Streams are capped at 16 MiB and sidecars at 512 KiB. Reaching a cap writes a
gap and seals the capture. Each input is bounded at 1 MiB. Captured strings are
bounded at 16,384 characters and collections at 256 items.

Python hook cores use `ASR_OUTPUT_DIR`, `ASR_CONTENT`, producer names of the form
`asr-hooks-<agent>`, extension `org.agentsessionrecord.hooks/v1`, the `/hook`
record type and the `redacted` loss. Shared credential rules and reference
encoding live in `python/agent_session_record`. References encode only the
characters required by ASR-011. A decision without a sourced subject omits it.
Metadata mode keeps a sourced approval subject after credential scrubbing.
Unknown native content blocks use `org.agentsessionrecord.native/content` parts.
These limits make capture best effort, without a completeness guarantee.

Install the writer, this package and the selected adapter into the agent's Python
environment from the repository root:

```sh
uv pip install ./python/agent_session_record ./plugins/python-core ./plugins/hermes
```

Replace the last path for another agent. Each adapter README describes native
registration and removal. Install commands require the agent's own environment.
The plugins do not install or configure a model provider.

Run the shared contract tests from the repository root:

```sh
uv run --all-packages pytest plugins/python-core/tests
```

The tests replay synthetic payloads from every adapter, compare deterministic
ASR samples and run the Node validator. They cover late input, explicit approval
choices, unpaired observations, lifecycle boundaries, redaction, contention,
queue overflow, silent failures and append-only resume.

## Test status

Live-test status: **partial**.
The current recorder passes offline regression checks. A live run of this
revision is pending.

At an explicit new session start, full-content capture observes Git metadata in
the supplied working directory. It keeps cwd, the repository root and available
branch, full HEAD and safe origin remote. A missing Git executable leaves cwd
available. Metadata mode withholds paths. A resume never replaces the header.
The shared hook extension is `org.agentsessionrecord.hooks/v1`. Python and
JavaScript packages derive these names from the same conventions document.
