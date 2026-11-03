# Shared recorder for remaining agent APIs

This core serves Goose, Pi, Cline, Kimi Code, Grok Build, the DeepSeek harness,
Crush, Mux and Amp. Each adapter projects a documented callback into a small
observation. The storage layer does no network I/O and returns no policy action.
Code, fixtures and source revisions live beside each agent's README.

## Storage and failure behavior

Set `ASR_OUTPUT_DIR` to a private directory. The directory must be owned by
the running user and have mode `0700`. Files have mode `0600`.
One file per native session uses a SHA-256 filename. Native identity stays
verbatim in its header. Every header declares `producer.method: recorder`.

The TypeScript writer creates each new stream. The shared command-hook layer
adds bounded cross-process append support. It uses the writer's deterministic
IDs and record validator, plus a private state file with byte count and call
identity sets. It checks that state against file length before resuming.
Complete lines are never rewritten. Restarting appends under the same native
identity. An interrupted state commit seals further writes with a gap when the
stream is intact. A partial write disables further writes to that session.
Use a fresh output directory and retain the incomplete capture for diagnosis. Do not repair either file by editing its existing bytes.

A PID-stamped lock serializes callbacks with a wait of at most 100 ms.
The next successful receipt appends a gap after lock contention or recovery.
Dead owners and locks older than ten seconds can be reclaimed automatically.
Receipt order is lock acquisition order where the API supplies no total order.

Limits are 1 MiB per event, 4096 distinct calls and 64 MiB per stream.
An oversized event produces a gap and later events can still be recorded.
Call and stream limits seal capture with a gap and a loss update. An intact
stream with an inconsistent checkpoint is sealed in the same way. Complete
lines are never changed. A torn tail leaves a local loss marker when no valid
gap can be appended. Retain it and select a new output directory.

Malformed command input, unavailable dependencies and filesystem errors fail
open. Commands keep stdout empty and exit zero. Fixed-code diagnostics stay in
a private local file. Oversized input and the 800 ms stdin deadline leave a loss
marker for the next callback. Hook configurations use a one second timeout.
Filesystem calls can still outlast a deadline on a stalled filesystem.

## Core mapping

Pre-tool arguments are observed requests. They stay under
`_meta.org.agentsessionrecord.hooks.requestedInput` in full mode.
They do not become core effective input. Post-tool arguments populate
`tool_result.input` only where the source establishes execution arguments.
Mux does not expose that guarantee and omits them.
Results are emitted at their completion observation and deduplicated by native
call ID. Pi waits for `tool_execution_end`, after result rewriting.
Other command-hook APIs can have later output rewrites. That loss is declared.

Explicit decisions become approvals only where the adapter has outcome
evidence. Requests, successful results and settings never become decisions.
No decider, person or grant scope is inferred. Unknown status stays unknown.
No missing exit code is replaced with zero.

Every record has receipt-time `ts`. Original session start is recorded only
when the callback establishes a fresh session. Explicit session end callbacks
may append `endedAt`. Turn stops, reloads, Pi runtime shutdown and Amp agent
end do not end the session. Capture without the original start emits a gap.

Lifecycle, permission requests, partial hook facts and other observations use
the declared `org.agentsessionrecord.hooks/v1` extension and its `/hook` record.
Only selected fields are retained. Extension records are evidence of callbacks
and do not claim to be a complete hook outcome ledger.
The validator warns about this extension and these record types.

## Content and losses

Content is omitted by default. Set `ASR_CONTENT=full` to retain available text,
structured tool input and selected output. Typed text parts keep their order
and bytes. Other parts are omitted. Their omission marks shortened records.
Structured non-content output is retained as metadata rather than presented
as invented model-facing text. No URI is fetched.

Known credential values from secret-named environment variables are excluded.
Sensitive keys and recognizable bearer and API key forms are also excluded.
Exclusion adds `redacted_content` to the declared losses and marks affected records.
Secret-valued native identities disable that receipt instead of changing
session identity or merging tool joins. Secret exclusion is best effort and does not establish
that a full capture is safe to share.

The common loss list includes reasoning, usage, native timestamps, incomplete
tool output, exit codes, file changes, commits, subagents, copies, model,
approvals, agent settings, offered tools, instructions, authorship, per-message
people, session user, hook outcomes, input rewrites, media, bounded capture,
assistant messages, native record IDs, parent lineage, triggers, lifecycle,
unmapped hook fields, result updates and history before capture.
Metadata mode also declares content and paths missing. These are incomplete
coverage declarations. They do not erase the facts that were recorded.

## Build and checks

Each agent's README explains installation and uninstall.
`build.mjs` makes a standalone local installation with bundled dependencies.
It refuses a nonempty output directory and does not publish anything.
Command configuration files with absolute paths must be built at their final
location. Goose and Mux manifests use plugin-root substitution.

Run `bash plugins/remaining-core/check.sh` from the repository root.
The checks cover all nine mappings, packaged entry points, folding order,
explicit versus absent approval evidence, secret exclusion, malformed input,
content omission, bounds, lock contention and append-only resume.
Synthetic native payloads and corresponding ASR samples live in each plugin's
`fixtures` directory. Never use personal saved history as a fixture.

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
