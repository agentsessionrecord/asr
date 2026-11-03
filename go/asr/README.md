# ASR Go types

This package contains generated ASR 0.1 shapes for all four v0 JSON Schemas.
It requires Go 1.24 or later. Types include each core record, shared payloads,
content variants, annotations, discovery and collection manifests.

Optional fields use `Optional[T]`. Its `Present` and `Null` flags distinguish
omission, an explicit null and a value. `Some(value)` supplies a value.
`Null[T]()` supplies an explicit null. The zero value omits an optional field.
Empty slices supplied with `Some` remain empty arrays. Fields use `omitzero`
to preserve these distinctions through `encoding/json`.

Numeric fields use `json.Number`. Arbitrary JSON and unknown fields use
`json.RawMessage`. This avoids rounding integers or decimal amounts during
reading and writing. Enums remain strings. Each object stores unknown fields
in `Extra`, and rejects extra fields that shadow known names.

These types describe structure. They do not enforce required fields, patterns,
conditional shapes or cross-record relationships. Validate files with the Node
validator. Producers must still encode large native values as strings under
the format's rules. Exact numeric storage in these types also supports reading
existing JSON without changing its value.

Generate the types with `python3 packages/types/scripts/generate.py` from the
repository root. Run `go test ./...` from `go/`. The tests round-trip example
records through generated types, then validate every emitted stream.

## Install and use

This module is local source. A Go consumer can use a local replacement:

```sh
go mod edit -require=github.com/agentsessionrecord/asr/go@v0.0.0
go mod edit -replace=github.com/agentsessionrecord/asr/go=/path/to/asr/go
```

Import `github.com/agentsessionrecord/asr/go/asr`. The package records no events
by itself and provides no native log discovery, writer lifecycle or redaction.
Live testing is not applicable. The synthetic round-trip and validator tests
above check the generated shapes.
