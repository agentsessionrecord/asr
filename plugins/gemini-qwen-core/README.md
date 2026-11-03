# Gemini and Qwen hook core

This small shared core handles the JSON stdin format used by both extensions.
It uses the TypeScript ASR writer to validate and serialize every transaction.
The build bundles the writer and validator with the recorder into each agent's
extension directory. No server or background process is needed.

```sh
pnpm --dir plugins/gemini-qwen-core test
```

## Storage

One native session has one append-only JSONL stream. The agent name and a hash
of the native identity form the filename. The native session ID remains
verbatim in the header. Record IDs derive from session identity, record type
and append position. A private sidecar keeps pending outcomes, completed call
IDs and the expected stream size across command invocations.

A PID-stamped process lock serializes each stream. Contention waits for at most 100 ms, then skips that
observation and leaves a loss marker. The next successful callback appends a
gap. Callback execution can arrive out of order from the harness. The recorder
uses accepted receipt order and does not claim a native total order.

Each transaction first uses the writer in a temporary private directory.
Only validated complete records are appended to the live stream. The temporary
header is discarded for an existing stream. No complete live line is changed.
The state checkpoint follows the append. A missing checkpoint, size mismatch,
or incomplete append stops further writes to that stream. An intact stream is
sealed with a gap and a loss update. Dead lock owners and locks older than ten
seconds are reclaimed with a gap at the next receipt. The
recorder never repairs existing bytes. Select a fresh output directory after
resolving a storage failure. Retain the old stream as evidence.

Files use mode 0600 and directories use mode 0700. Output directories must be
private and owned by the current user. Stream symlinks are refused. There is
no retention service. Uninstalling an extension preserves recordings.

## Failure and content limits

Commands stay silent and exit successfully, including on malformed payloads,
missing output configuration or I/O failures. The shell wrapper also suppresses
startup failures. Hooks make no network requests and return no tool changes,
permission decisions or injected content. Hooks run synchronously with short
local work. The stream lock wait is bounded to 100 ms. Qwen command timeout is one
second and Gemini command timeout is 1000 milliseconds.

Input is capped at 1 MiB. An oversized event produces a gap and capture continues.
Oversized command input and the 800 ms stdin deadline leave a loss marker for
the next callback. State is capped at 2 MiB and each stream at 64 MiB.
Individual strings are capped at 65536 characters. Omitted text is marked
truncated and redaction losses are declared. Deep values and binary content
are omitted. Large native numbers use their exact source representation as
strings. Core durations outside the safe numeric range are omitted.

Metadata capture omits prompts, replies, input and output text. Full capture
keeps available content after secret exclusion. The recorder reads neither
transcripts nor global settings, repository state or credential files.
It excludes known credential values present in its own hook environment.
It does not promise complete detection of secrets in arbitrary text.

The declared vendor extension preserves hook occurrence, request metadata and
native Google content parts. Offline validators warn about its unknown
extension and event type. These warnings are expected. Missing call results
in isolated test cases also produce expected pairing warnings.


A `SessionStart` with source `startup` or `clear` can establish the start time
before the header is written. Instruction preambles wait in the private
checkpoint for that start or another callback, up to eight events and 64 KiB.
They keep their receipt times and order. A fresh start after those preambles
has no missing-history gap. A resume or tool callback without a fresh start
begins with a gap and declares `history_before_capture` missing. A start after
the header keeps its receipt as a hook record and does not change `startedAt`.

Conventions and credential patterns come from the shared writer package.
The extension is `org.agentsessionrecord.hooks/v1`, the hook record type is
`org.agentsessionrecord.hooks/hook` and the metadata key is
`org.agentsessionrecord.hooks`. Producers use `asr-hooks-<agent>`.

## Setup and test status

Install the repository dependencies with `pnpm install --frozen-lockfile`.
Build and register an adapter with the
[Gemini CLI](../gemini-cli/README.md) or [Qwen Code](../qwen-code/README.md)
instructions. The core has no independent agent registration.

Synthetic storage and mapping tests run with
`pnpm --dir plugins/gemini-qwen-core test`. They cover loss markers, recovery,
content policy and conservative tool pairing. Independent live testing is not
applicable to this shared core. Each adapter records its own host test status.

At an explicit new session start, full-content capture observes Git metadata in
the supplied working directory. It keeps cwd, the repository root and available
branch, full HEAD and safe origin remote. A missing Git executable leaves cwd
available. Metadata mode withholds paths. A resume never replaces the header.
The shared hook extension is `org.agentsessionrecord.hooks/v1`. Python and
JavaScript packages derive these names from the same conventions document.
