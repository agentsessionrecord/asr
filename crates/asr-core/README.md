# Rust ASR core

This crate provides serde record fields for ASR 0.1 and helpers for JSONL readers
and append-only writers. Unknown records, fields and open enum strings survive a
round trip. Numbers use exact JSON tokens. Settings distinguish absent values
from supplied null values.

Run `python3 crates/asr-core/generate.py` from the repository root to regenerate
record fields from `schema/v0/agent-session.schema.json`. Add `--check` to detect
a stale generated file. The schema remains the authority for validation constraints.

`Writer::new` writes the header once. `append` adds one complete JSON line.
It checks required record fields, IDs, duplicate results and input exclusivity.
Use the Node validator for all schema and cross-record checks.
An `IdentityStore` implementation can keep writer IDs on disk.

`SessionState` applies settings in stream order. It unions known losses, appends
repositories, replaces offered tools and session totals, and clears supplied null
settings. A policy change invalidates the earlier asking summary when needed.
`effective_input` accepts a result only after the caller establishes unique pairing.

`jsonl::Reader` bounds lines, reports corrupt complete lines and defers incomplete
tails. It rejects duplicate keys at every nesting depth. It never fetches content
or executes text in a stream.

## Install and use

Use the Rust toolchain required by the root `Cargo.toml`. Add this local crate
to a Rust consumer with `cargo add asr-core --path /path/to/asr/crates/asr-core`.
It is a library and has no separate agent registration or command.
The [writer implementation](src/writer.rs) and [reader implementation](src/jsonl.rs)
show the public API. The CLI and converter crates use both.

## Tests and status

```sh
cargo test -p asr-core
python3 crates/asr-core/generate.py --check
```

Synthetic tests cover exact JSON values, unknown fields, ordering, settings,
identities, corrupt lines and writer checks. Independent live testing is not
applicable. This library records only the facts supplied by its caller.
It does not redact secrets or establish complete capture. Validate finished
streams with the Node validator.
