# ASR Python types and writer

This package contains generated ASR 0.1 Pydantic v2 models and a small append-only
writer. Pydantic keeps unknown fields and distinguishes omitted fields from
explicit null through `model_fields_set`. That distinction supports settings
updates without adding a custom dataclass sentinel.

Import generated models from `agent_session_record.models`. Python field names
use snake case. JSON aliases keep the schema's field names. To serialize a model
without adding unknown facts, use
`model_dump(by_alias=True, exclude_unset=True)`. The writer does this for you.
The generated models describe structure. The bundled JSON Schemas check the
remaining per-record constraints when writing. All references resolve locally.

`Writer(path, header)` creates one new file with append and exclusive creation
flags and mode `0600`, then writes its header. The header can be a generated
`Session` model or a mapping. Supply the recorded agent, native session ID and
producer. A mapping can omit `type` and `formatVersion`.
`append(record)` writes one completed record and returns its ID.
`update(fields)` appends `session_info`. `close()` closes the file. A context
manager closes it on exit. Calls on one writer are serialized with a lock.

`Writer.resume(path, max_bytes=...)` reopens a complete stream for append.
It validates the existing records and restores ID positions, declared losses
and completed call IDs. Invalid, incomplete or oversized files stay unchanged.
The default size bound is 8 MiB. It refuses symbolic links on systems that
support that check. The caller must exclude other processes while reopening
and writing. `position` reports the number of completed records.

Supply a unique native record ID as `id` when available. Otherwise, IDs derive
from session identity, record type and append position. The derivation matches
the TypeScript writer. Supplied duplicate IDs fail before a write. Append in
source completion order. For a snapshot approval with no source position,
append it immediately before its result. A result can record effective input
without changing the earlier call.

Omitted settings stay omitted. Explicit `None` becomes JSON `null` and clears a
setting. Tool lists and declared losses are written as supplied. Empty lists,
false, zero and empty strings remain distinct from omission. The writer invents
no times, models, outcomes or session end. Declare `model` in `missing` before
an inference without a model. A copied prefix must end at an appended record
after the header and before close.

Integers outside the safe JavaScript integer range become decimal strings,
including native values nested in tool input or metadata. Large floats and
non-finite floats are rejected. Core numeric fields stay JSON numbers. Large
integers in those fields fail validation after string conversion. For a core
count outside the safe integer range, omit the core field and keep the exact
decimal string under your reverse-DNS key in `_meta`. Declare the loss in
`missing` if a reader would otherwise miss it. The writer never rounds the value
or emits the wrong shape.

A failed record leaves the existing bytes and ID position unchanged. An I/O
failure stops further appends and may leave an incomplete final line. The writer
never rewrites a line or repairs a stream. Use one writer per file. Close adds no
end event and makes no durability claim. The caller must exclude known secrets
and supply source evidence. Validation does not establish safety to share.

Run the [30-line example](examples/session.py) from the repository root:

```sh
uv run --package agent-session-record python python/agent_session_record/examples/session.py /tmp/example-python.jsonl
node tools/validator/bin/asr-validate.js /tmp/example-python.jsonl
```

The output path must not already exist. Generate types and check all libraries
with the commands in `packages/types/README.md`.

## Install and test status

Use Python 3.11 or later and uv. From the repository root:

```sh
uv sync --package agent-session-record --group dev
uv run --package agent-session-record pytest python/agent_session_record/tests
```

For an agent's existing environment, install the local package with
`uv pip install ./python/agent_session_record`.
The local example and synthetic streams pass the Node validator.
Live-test status: **not-applicable** for offline writer checks. No model request is
needed. The writer cannot discover agent sessions, restore missing events or
remove secrets automatically.
