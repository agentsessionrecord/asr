# Load Parquet tables

Load one complete dataset into a fresh namespace or replace every ASR table.
Appending exports can double count a session. Keep the same permissions and
retention rules as the original files. JSON columns remain strings in every
engine. `raw_json` is the exact source representation.

## DuckDB

The local loader replaces fixed ASR tables in a single transaction. It leaves
other tables in that database alone. Select a database dedicated to this data.

```bash
uv run --package asr-tables asr-tables duckdb ./tables ./sessions.duckdb
duckdb ./sessions.duckdb < exporters/tables/queries/cost-by-user-agent.sql
```

The Python package also exposes `asr_tables.loaders.load_duckdb(dataset, database)`.
DuckDB 1.4.4 is pinned and tested. You can query the files directly with
`read_parquet('./tables/inferences.parquet')`.

## ClickHouse

Create a dedicated empty database on a local server. Generate the fixed schema
and insert each Parquet file. This example uses the default local endpoint.

```bash
clickhouse-client --host 127.0.0.1 --query 'CREATE DATABASE asr'
uv run --package asr-tables asr-tables clickhouse-ddl > tables-schema.sql
clickhouse-client --host 127.0.0.1 --database asr --multiquery < tables-schema.sql
for table in sessions records messages tool_calls tool_results approvals \
  file_changes vcs inferences session_updates settings_changes gaps links diagnostics
do
  clickhouse-client --host 127.0.0.1 --database asr \
    --query "INSERT INTO $table FORMAT Parquet" < "tables/$table.parquet"
done
clickhouse-client --host 127.0.0.1 --database asr --multiquery \
  < exporters/tables/queries/cost-by-user-agent.sql
```

The generated schema uses nullable strings, integers, booleans and
`Decimal(38,18)`. It uses MergeTree with an empty sort tuple so ingestion preserves
every exported record. Query order still requires `ORDER BY session_ref, position`.
Load into a fresh database for each snapshot. A MergeTree append does not deduplicate
sessions or records. ClickHouse 25.8 is tested with the local container script.

## BigQuery

These are load instructions, not a live-tested cloud integration. Configure your
own project and dataset. Use a location and access policy appropriate to this
data. The command below is illustrative and is not run by the exporter.

```bash
bq load --replace --source_format=PARQUET --decimal_target_types=BIGNUMERIC \
  'example-project:asr.inferences' ./tables/inferences.parquet
```

Repeat for every table in the manifest, using the filename stem as the destination
table name. Use a new dataset or load all replacement tables before readers use
the snapshot. `--replace` prevents repeated imports from accumulating old rows.
Parquet types provide the schema. Decimal values require BIGNUMERIC because their
scale can exceed NUMERIC's nine fractional digits. JSON and timestamps stay
strings. Use backtick-qualified table names in the SQL examples.

Keep `cost_amount_text` and `raw_json` when exact numeric values exceed a typed
decimal range. Do not convert these strings to floating point for accounting.
Session and record keys are logical keys. Enforce uniqueness during ingestion.

## Snowflake

These are load instructions, not a live-tested cloud integration. Use a private
stage and dedicated schema. The following example loads only the inference table.
Choose your own database, schema, warehouse and stage permissions first.

```sql
CREATE FILE FORMAT asr_parquet TYPE = PARQUET USE_LOGICAL_TYPE = TRUE;
CREATE STAGE asr_stage FILE_FORMAT = asr_parquet;
PUT file:///work/tables/*.parquet @asr_stage AUTO_COMPRESS = FALSE;
CREATE TABLE inferences USING TEMPLATE (
  SELECT ARRAY_AGG(OBJECT_CONSTRUCT(*))
  FROM TABLE(INFER_SCHEMA(
    LOCATION => '@asr_stage/inferences.parquet',
    FILE_FORMAT => 'asr_parquet', IGNORE_CASE => TRUE
  ))
);
COPY INTO inferences FROM @asr_stage/inferences.parquet
  FILE_FORMAT = (FORMAT_NAME = asr_parquet)
  MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE;
```

Run the PUT command through a client that supports local file upload, such as
SnowSQL. Repeat CREATE TABLE and COPY for each manifest table. Use a fresh schema
and stage prefix for each snapshot. Snowflake's loaded-file tracking does not
deduplicate session records across renamed or changed files. NUMBER supports the
portable decimal precision. Verify inferred `COST_AMOUNT` is `NUMBER(38,18)`
before loading. JSON values remain VARCHAR so unknown fields and exact numbers
survive without conversion to VARIANT. The SQL examples use unquoted column names
and work with the inferred uppercase names.
