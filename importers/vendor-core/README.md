# Shared vendor importer core

This local Python library supports the four vendor and checkpoint importers.
It supplies exact JSON parsing, source timestamps, inclusive token arithmetic,
deterministic record IDs and private ASR output through the Python writer.

Install from the repository root with Python 3.11 or later and uv:

```sh
uv sync --all-packages
```

Each importer has its own command and source profile.
See [Anthropic](../anthropic-compliance/README.md),
[Codex logs](../openai-codex-logs/README.md),
[Copilot](../copilot/README.md) and [Entire](../entire/README.md).

## Safety and losses

All source content is untrusted data.
These importers never run recorded commands or fetch recorded links.
They create new files with owner-only permissions and refuse existing outputs.
Malformed native JSONL lines and incomplete final lines become gaps.
Duplicate JSON object keys and non-finite numbers are rejected.
Large native numbers and exact decimals are kept as strings in metadata.
Unsafe core counts are omitted and usage remains a declared loss.
Missing values are never replaced with zero or success.

Known credential fields, common provider tokens, bearer tokens, private keys,
URL credentials and opaque provider state are filtered from content and metadata.
The filter also inspects JSON encoded inside strings.
Filtered records carry `truncated: true` and declare `secrets` in `missing`.
This filter cannot identify every secret or establish that output is safe to share.

Source input is capped at 32 MiB. Projection is capped at 64 MiB and 100,000 records.
Credential scanning has separate depth and value limits. Capacity failures stop
the import before output is written. See [the threat model](../../SECURITY.md).

Repeated tool results with a reused call ID remain unpaired.
Their native join key stays in metadata and the ambiguity is a declared loss.
A call with no result keeps an unknown outcome.
Unknown native shapes stay in metadata with a gap or a loss update.
These tools do not derive blame or assert completeness.

## Checks

```sh
uv run --all-packages pytest importers/vendor-core/tests \
  importers/anthropic-compliance/tests importers/openai-codex-logs/tests \
  importers/copilot/tests importers/entire/tests
```

Tests use synthetic vendor fixtures, both native agent samples and the ASR
samples and examples. Each produced stream is checked by the Node validator.

## Test status

The synthetic contract and validator checks above cover the shared library.
Independent live testing is not applicable. Each importing command states its
own source and service coverage in its README. The core cannot obtain vendor
exports or recover content that their source omitted.
