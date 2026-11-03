# JSON Schemas

These draft 2020-12 schemas describe Agent Session Record format 0.1.
They are generated from `tools/validator/src/schema/build.js`.

| File | Validates |
|---|---|
| [agent-session.schema.json](v0/agent-session.schema.json) | One session record, including its envelope. |
| [annotation.schema.json](v0/annotation.schema.json) | One annotation and its known payload. |
| [discovery.schema.json](v0/discovery.schema.json) | The discovery file in the [integration guide](../guides/integration.md). |
| [manifest.schema.json](v0/manifest.schema.json) | The optional collection receipt in the [audit guide](../guides/audits.md). |

The schema IDs use `https://agentsessionrecord.org/schema/v0/`. Load the session
schema alongside annotation and discovery schemas to resolve their shared definitions locally.
The manifest schema is independent and has no numbered ASR requirements.
A manifest requires the v0 `$schema` URL. Every status except `received` requires
a reason, including unfamiliar statuses. The validator adds chronology and
unknown-status warnings to those shape checks.
Enable RFC 3339 `date-time` and `asr-base64` format checking in your schema implementation.
`asr-base64` checks the RFC 4648 alphabet, a length divisible by four and up to
two trailing padding characters. It accepts an empty string and does not restrict
padding bits. The reference implementation uses a loop with constant stack space.
Validation needs no network access.

## Record shapes

The session schema checks the envelope, then selects a shape for each known
`type`. Unknown types receive envelope checks. Vendor type names follow
`<reverse-dns>/<name>`. Objects allow unknown fields and enums accept unknown
strings. Unknown content parts retain their type and data. An unknown file hash
algorithm is preserved without imposing a known algorithm's length.

Shared definitions cover IDs, session references, non-empty person identities,
settings, tool definitions, paths, content, repositories, lineage, file states, models, usage,
cost and pull requests. Agent short names
come from the [agent list](../agents/agents.json). Reverse-DNS names also work.
The schema cannot establish domain ownership or whether a fact came from the
source. Native model values on summary annotations have no prescribed shape.

Schema nodes carry `x-asr` requirement labels. The reference validator uses them
for diagnostics. Other schema validators can ignore that annotation.

The schemas check per-record constraints such as exclusive input forms and the
source path on a move or copy. The [validator](../tools/validator/README.md) also
checks framing, duplicate IDs, tool and approval pairing, parent counts, rewrite endpoints,
copy boundaries and annotation corrections across the file.

## Generate and check

Run these from the repository root:

```sh
pnpm --dir tools/validator run build
pnpm --dir tools/validator run check:generated
```

The second command fails if a generated file differs from its source. The full
`pnpm --dir tools/validator run ci` also checks examples and conformance fixtures.
