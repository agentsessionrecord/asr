# ASR TypeScript writer

`@agent-session/writer` writes one new ASR 0.1 session file. It uses synchronous
Node file writes. It opens the file with append and exclusive creation flags and
mode `0600`. An existing file is never replaced.

`new Writer(path, header)` writes the header. Supply the recorded `agent`,
`sessionId` and `producer`. The writer supplies `type: "session"` and
`formatVersion: "0.1"` when omitted.
`append(record)` writes one completed record and returns its ID.
`update(fields)` appends a `session_info` record. `close()` closes the file.

Pass a unique source record ID as `id` when the source supplies one. Otherwise,
the writer derives a stable ID from session identity, record type and append
position. Keep source order stable when exporting again. Duplicate supplied IDs
fail before a write. Derived IDs avoid collisions with supplied IDs.

Append events at their source completion positions. The writer does not sort
by time or fold observations. For a snapshot approval with no source position,
append it immediately before the result it concerns. A result can supply
`input` or `inputText` learned at completion without changing its earlier call.

Omit unknown facts. Pass `null` to clear a known setting. The writer keeps
omitted fields, nulls, false, zero and empty lists distinct. It writes tool lists
and loss updates as supplied. It never invents a time, model, outcome or session
end. Declare known losses in the header or the next update. Declare `model`
before writing an inference without a model. A copied prefix must name a record
that is appended after the header and before close.

Use strings for native values that may exceed the safe integer range. Bigints
are converted to decimal strings throughout the record. Unsafe JavaScript
numbers are rejected because their original value may already be lost.
Core numeric fields stay JSON numbers. A large integer in such a field is
rejected after string conversion. For a core count outside the safe integer
range, omit the core field and keep the exact decimal string under your
reverse-DNS key in `_meta`. Declare the loss in `missing` if a reader would
otherwise miss it. The writer never rounds the value or writes the wrong shape.

Schema failures, duplicate IDs, duplicate results and inconsistent VCS facts fail
before writing. Unknown JSON fields and values remain available. Non-JSON values
are rejected. After an I/O error, the writer refuses further appends. The file
may end with an incomplete line. It never repairs or rewrites that line.
Use one writer per file. Close flushes no extra record and makes no durability
claim. The caller must exclude known secrets and supply only facts it observed.
Passing validation does not establish that a file is safe to share.

The [30-line example](examples/session.ts) writes settings, a tool list, an
approval, a result and explicit clearing updates:

```sh
node --experimental-strip-types packages/writer/examples/session.ts /tmp/example-ts.jsonl
node tools/validator/bin/asr-validate.js /tmp/example-ts.jsonl
```

Build the packages first with `bash packages/types/scripts/check.sh` from the
repository root. The output path must not already exist.


## Shared recorder helpers

`encodeReferenceComponent` escapes the ASR-011 reserved characters with uppercase
UTF-8 bytes. `sessionReference(agent, sessionId, namespace?)` builds a reference.
Native header identities remain unchanged. Unreserved punctuation and Unicode
remain literal so producers use the same join keys.

`isSecretKey`, `environmentSecrets` and `redactSecrets` share credential names
and recognizable token forms. Recorders use these helpers for structured fields,
text and property names. Ordinary token counts and author environment fields
remain available. Callers still choose their content limits and exclude opaque
provider state. The writer itself does not automatically redact records.

An approval can contain only its required `decision`. Omit a missing `subject`.
A linked decision covers the whole call unless the source names a narrower request.

The `@agent-session/writer/capture` entry supplies incremental command-hook
storage, PID-stamped locks, loss markers and fixed-code local diagnostics.
Command locks wait for at most 100 ms. Dead owners and locks older than ten
seconds can be recovered. In-process adapters reclaim only dead owners because
they hold a lock for the entire attachment.

JavaScript hook recorders use these shared conventions. Regression tests check
the cores against the same constants.

| Item | Value |
| --- | --- |
| Output directory | `ASR_OUTPUT_DIR` |
| Content choice | `ASR_CONTENT`, `metadata` or `full` |
| Producer | `asr-hooks-<agent>` |
| Extension | `org.agentsessionrecord.hooks/v1` |
| Hook record type | `org.agentsessionrecord.hooks/hook` |
| Metadata key | `org.agentsessionrecord.hooks` |
| Loss names | `redacted_content`, `content`, `session_lifecycle`, `dropped_callbacks`, `capture_stopped` |

Storage or capacity failures seal an intact stream with a gap and a loss update.
A sealed file is not resumed. A torn final line cannot accept another valid
record without changing earlier bytes. That case leaves private loss and sealed
markers and a local diagnostic. Keep that capture and use a new output directory.
Command input without a usable session ID leaves an agent-level loss marker.
The next accepted callback for that agent declares the loss. It cannot identify
which session lost the input. Capture state from an older recorder version is
sealed before using the new extension conventions.

## Install and test status

Use Node.js 22.13 or later and pnpm 12.11.2. From the repository root:

```sh
pnpm install --frozen-lockfile
pnpm --filter @agent-session/types build
pnpm --filter @agent-session/writer build
pnpm --filter @agent-session/writer test
```

The local example and property-generated sessions pass the Node validator.
Live-test status: **not-applicable** for these offline writer checks. No agent inference is
needed. The package cannot discover native sessions or recover missing source
facts. Its shared helpers are opt-in and the writer does not redact by itself.
