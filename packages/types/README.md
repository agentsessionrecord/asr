# ASR types

`@agent-session/types` provides TypeScript shapes generated from all four JSON
Schemas in `schema/v0`. Python models live in `python/agent_session_record`.
Go types live in `go/asr`.

The generator uses Python's standard library and Go's `gofmt`. Run these commands
from the repository root with Go 1.24 or later on `PATH`:

```sh
python3 packages/types/scripts/generate.py
python3 packages/types/scripts/generate.py --check
```

The check fails when any generated file or bundled Python schema is stale.
Every generated language file records a digest of the schema inputs.
The tests also check that a changed schema fails this check.
Do not edit generated files by hand.

Import types from `@agent-session/types`. `KnownRecord` is the union of the ten
core records. `ASRRecord` also accepts unknown records through `Envelope`.
Enums remain strings. Objects retain open fields. Content and annotation types
include concrete variants such as `TextPart` and `TitleAnnotation`.

These are structural types. Patterns, conditional requirements, exclusive fields
and relationships still need the validator. The writer checks these constraints
before appending each record where the available history permits it.

To install and check these libraries from a fresh checkout:

```sh
pnpm --filter asr-workspace --filter @agent-session/types --filter @agent-session/writer --filter @agent-session/validate install --frozen-lockfile
uv sync --package agent-session-record --group dev
bash packages/types/scripts/check.sh
```

The same checks run through `scripts/ci.sh`.

## Use and test status

Build the local package with `pnpm --filter @agent-session/types build` after
installation. Import its types in a TypeScript consumer:

```ts
import type { ASRRecord } from '@agent-session/types';
```

The package records no session data. It supplies shapes and cannot validate
runtime content. Generation drift and type checks run in the library check
above. Independent live testing is not applicable to generated types.
