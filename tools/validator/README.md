# ASR validator

`asr-validate` checks Agent Session Record 0.1 session streams, annotations and
optional collection manifests.
It checks JSONL framing, record schemas and relationships inside one file.
It never queries Git, the network or native agent storage. Passing validation
establishes structure, not source faithfulness or safety to share.

## Run

Use Node.js 22.13 or later and pnpm. From the repository root:

```sh
pnpm --dir tools/validator install
node tools/validator/bin/asr-validate.js examples/coding-session.jsonl
node tools/validator/bin/asr-validate.js --json --summary examples/
node tools/validator/bin/asr-validate.js --json examples/annotations.annotations.jsonl
node tools/validator/bin/asr-validate.js examples/collection.manifest.json
node tools/validator/bin/asr-validate.js - < examples/minimal.jsonl
node tools/validator/bin/asr-validate.js conformance conformance/fixtures
```

The package exposes the same command as `asr-validate`. A filename ending in
`.annotations.jsonl`, or a first record with `type: "annotation"`, selects
annotations. Standard input uses the first record to select the format.
A filename ending in `.manifest.json`, or a document beginning with the manifest's
`$schema` property within the first 4 KiB, selects the collection manifest. It is one JSON document and
does not require JSONL framing or a final newline.

The exit code is `0` when validation passes, `1` for validation errors or fixture
mismatches, and `2` for invalid command arguments or an input failure. Warnings
alone pass. `--json` works for files, directories, standard input and conformance cases.

Directory validation recursively reads `.jsonl` and `.manifest.json` files, one
file at a time. It skips symlinked entries and other filenames. Each file has
its own relationship indexes. An input failure is counted without stopping the
remaining files. An empty directory is an input failure. JSON output streams a
`files` array followed by an aggregate `summary`.

`--summary` omits individual diagnostics and reports counts by severity and code.
For a directory it also omits per-file reports. Combine it with `--json` for one
aggregate JSON object. It does not change validation rules or suppress warnings.

## Diagnostics

Every validation diagnostic has a severity, requirement ID, code, physical line,
JSON pointer and message. Lines start at one. An empty pointer refers to the
whole record. JSON output also reports the file kind, complete record count,
error count and warning count. It does not include the transcript content.
Manifest diagnostics have no ASR requirement IDs and locate the document at
line one with JSON pointers. The manifest requires its v0 `$schema` URL and
a reason for every status except `received`. The validator warns about unknown
statuses, a window whose end is not after its start, and receipts outside the
window. The start is included and the end is excluded. Digest correspondence,
cross-file window chains, uploader authentication and completeness are not checked.

Errors cover the [conformance checks](../../spec/conformance.md): malformed
complete lines, duplicate keys, headers, schema failures, duplicate IDs, commit
and file hash shapes, consistent VCS hash lengths, parent counts, rewrite endpoints, copy boundaries and
annotation corrections. Malformed complete lines are reported and skipped so
later records can still be checked.

Warnings report an incomplete final line, unknown types or extensions, a tool
call without a name, unresolved inference links and unpaired tool activity.
An approval with a `callId` but no unique matching call also warns. A decision
without a call ID needs no matching call or result.
Duplicate call IDs leave the calls and their results unpaired. Duplicate result
call IDs are errors. File changes and VCS records
cannot contain both `callId` and `actor`. Session-only references have no record fragment.
Forward references are checked after all complete lines have been read. An incomplete final line
is deferred even if its current bytes parse as JSON.

Unknown fields, enum values and content parts remain unchanged. Vendor records
receive envelope checks and a warning. The validator also accepts unfamiliar
core type names, since unknown types are not errors. Vendor type names still
follow the reverse-DNS naming rule. No named extensions are interpreted.

An absent related session is allowed. The validator does not infer tool outcomes,
expand commit prefixes or assign blame. The CLI streams session and annotation
records. Its memory grows with the largest line and the IDs and line references
needed for relational checks. Without `--summary`, it also keeps one file's
diagnostics for sorting. Summary mode keeps only diagnostic counts. A collection
manifest is a single JSON document and is read into memory.

## Library

Import the validation functions from `@agent-session/validate`.

- `validateStream(chunks, options)` accepts an async iterable of byte chunks.
- `validateFileStream(filename, options)` reads a file through that same path.
- `validateDirectory(directory, options)` is an async iterator yielding each file's report, or `{file, error}` for an input failure.

These APIs return `valid`, `kind`, `recordCount`, `errors`, `warnings`, `counts`
and `diagnostics`. Set `summary: true` to omit diagnostics. They retain no record
content and never reserialize numbers. `filename` and `mode` select the format.
Use `mode: "manifest"` for a manifest without a recognizable filename or leading
schema property. Explicit modes are `session`, `annotations` and `manifest`.

The synchronous `validate`, `validateFile` and `validateRecord` APIs remain
available for callers that need parsed records.
`validate(bytes, { filename, mode })` accepts UTF-8 bytes or a string. The default
mode is `auto`. Explicit modes are `session`, `annotations` and `manifest`.
`validateManifest(bytes)` checks a manifest directly.

The result has `valid`, `kind`, `records` and `diagnostics`. Each complete parsed
record includes its physical line, parsed `value` and `raw` JSON text. Use `raw`
when retaining exact numeric spellings beyond JavaScript's number precision.
Numeric shape checks use the source spelling without imposing a precision limit.
The parsed JavaScript `value` can round a large number. Preserve `raw` when
retaining or forwarding that record.
`validateRecord(record)` performs only envelope
and per-type schema checks, which suits excerpts. It detects annotations by type.
Pass `discovery` as its second argument to check a discovery object.
Pass `manifest` to check an already parsed collection manifest.

## Development

Run all validator checks with one command:

```sh
pnpm --dir tools/validator run ci
```

This checks generated schemas and requirements, runs `node --test`, validates
every example, compares conformance fixtures and checks documentation examples.
It also validates every ASR sample, native sample JSON and the README file digests.
The documentation check covers Markdown and MDX in `spec/`, `guides/`, `agents/`,
`site/pages/`, `examples/`, the white paper and repository READMEs.

A JSON or JSONL block beginning with a session header is checked as a stream.
Other record blocks are checked as excerpts without file-level relationships.
Discovery and manifest JSON use their own schemas. Blocks marked `json native` or `jsonl native`
receive JSON syntax and duplicate-key checks without ASR schema checks. Documentation
examples must have no errors or warnings.

`pnpm --dir tools/validator run build` regenerates the four public schemas and
`src/requirements.js`. The requirement builder matches the conformance table
against every numbered definition in `spec/*.md`. The schema builder checks
agent short names against `agents/agents.json`.

See the [schema guide](../../schema/README.md), [examples](../../examples/README.md)
and [fixture guide](../../conformance/README.md).

## Test status

The CI command above covers the conformance suite, streaming and CLI behavior,
all sample streams and documentation examples. Live agent testing is not
applicable to this offline checker. It records no new session and makes no
model requests. Format validation cannot establish source completeness,
authenticity, correct attribution or the absence of secrets.
