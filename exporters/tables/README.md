# ASR data tables

Convert ASR 0.1 session files to local Parquet tables. The exporter keeps messages,
tool calls and results, approvals, file changes, version control actions, model
calls, settings changes and gaps. Python 3.11 or later is required.

## Install and run

From the repository root:

```bash
uv sync --package asr-tables
uv run --package asr-tables asr-tables export \
  examples/subagent/parent.jsonl examples/subagent/child.jsonl --output ./tables
uv run --package asr-tables asr-tables duckdb ./tables ./sessions.duckdb
```

For a standalone install, use `pip install ./exporters/tables`. The installed
command is `asr-tables`. No service or account is needed.

Pass explicit session files. The destination must be new. Output contains one
Parquet file for every table, including empty tables, and a `manifest.json` with
schema version 1 and row counts. Directories use mode 0700 and files use 0600 on
systems that support these modes. Treat all exported data as sensitive.

The exporter reads complete LF-terminated records in file order. Malformed
complete lines produce code-only diagnostics and are skipped. A final line
without LF stays incomplete. Neither case contributes facts. A missing header,
unsupported version, duplicate record ID or conflicting revision is an error.
The CLI prints counts and diagnostic codes. It never prints source content.

The same byte-identical session supplied twice is counted once. Different files
with the same full session reference are rejected. Select the desired revision
before export. Create a fresh dataset for each snapshot. Do not append snapshots
to an existing analytics table.

## Interpretation

Each record retains its physical `position`, even when a malformed line was
skipped. Sort by that column within a session. Timestamps are source strings and
never determine order. `records.raw_json` preserves every accepted source object
verbatim, including unknown types, fields, content parts and numeric spelling.
Typed columns and nested JSON strings support queries without losing that source.

`original` is false for individual copies and the complete copied prefix through
`parent.copiedThrough`. A missing copy boundary withholds credit from every record
after the header and emits a diagnostic. Unavailable copy sources stay unresolved.
Missing copy detection is reported through `missing_json` without changing the
credit rule. Copies remain available for search.

Use only original `inferences` for additive usage and cost. New child calls count
as the child's work. Input tokens already include cache reads and writes. Output
tokens already include reasoning. Do not add those components again. Unknown
counts and costs stay NULL. Recorded zero values stay zero.

Session totals remain in `session_updates` and the latest original totals in
`sessions`. Each supplied total replaces the preceding total of that kind.
Never add these totals to per-call figures or sum successive totals. Do not add
child usage to a parent total whose `includes_subagents` is true or NULL. The cost
total has no independent scope flag, so this exporter offers no additive cost
report based on session totals.

Tool results join only one matching call. Duplicate call IDs and duplicate
results leave outcomes unknown and results unpaired. Results without a call ID
stay unpaired. Effective result arguments override call arguments, including
JSON null and empty strings. Approvals join only a unique call. Approval does not
establish execution or success. All decisions remain separate rows.

Settings updates apply field by field. Null clears a fact. Model settings merge
field by field. An outer sandbox object replaces the whole preceding object.
A change to mode, approval or sandbox without `asks` clears the earlier summary.
Configured settings never fill missing inference settings. Offered tools replace
the whole list. Repositories and known losses accumulate.

`links` retains both parent-side and child-side subagent references. Either side
can establish a relationship. It also retains copy sources, message senders and
inference references, including unresolved targets. The SQL examples combine
subagent links without requiring both files.

The tables preserve recorded actions and file evidence. They do not derive blame,
resolve commit prefixes or claim line authorship. A sessions-per-commit query
reports recorded associations. Repository checks from the spec are still required
to grant edited-by or committed-by credit. A session's user is a grouping label.
It does not establish who wrote a prompt or made a commit.

## Load and query

See [the column reference](COLUMNS.md) for keys and types and
[load instructions](LOADERS.md) for DuckDB, ClickHouse, BigQuery and Snowflake.
The [queries](queries/) include cost by user and agent, approvals by decider,
sessions per commit, separate session totals and subagent relationships.

The cost query separates currency, cost source and served and requested models.
It counts missing cost and exact amounts outside the portable decimal range.
An absent cost is unknown. Do not interpret a NULL sum as free work.

## Safety and limits

All content is untrusted data. Export does not fetch resource URIs, open recorded
paths, run recorded commands or read Git repositories. The DuckDB loader uses
fixed table names and bound file arguments. Load commands act only when the user
runs them. BigQuery and Snowflake instructions have no tested cloud connection.

This reader does not validate every ASR schema field. Validate inputs with
`node tools/validator/bin/asr-validate.js` before relying on their structure.
Validation does not establish that data is safe to share. No automatic redaction
is performed. Exclude known secrets before export and apply access and retention
rules to both the source and its derived tables.

Annotations are outside this entry point. Pass session streams only. Revisions
must be selected explicitly. Export holds the selected records and tables in
memory, so split large collections into bounded batches with disjoint sessions.
Do not sum overlapping batches. Text is stored without truncation. Numeric
values beyond a typed column's range remain in the raw JSON. Unsupported core
integer sizes fail the export rather than wrap or round.

## Tests

```bash
uv run --package asr-tables pytest exporters/tables/tests
uv run --package asr-tables python exporters/tables/tests/clickhouse_smoke.py
```

The first command runs synthetic fixtures and every session in `examples/` and
the ASR files in `samples/`. It validates committed fixtures and tests DuckDB
loads and queries. The second uses Docker to start a local ClickHouse 25.8
container with no network and no published ports. It checks every table, compares
accounting queries with DuckDB and removes the container, including on failure.
Set `ASR_TABLES_DOCKER` to the Docker command needed by your local setup.
CI runs the first command. The container test is explicit so ordinary CI does
not require Docker.
