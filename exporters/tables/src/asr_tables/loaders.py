"""Fixed table names and quoted user-selected local paths only."""

from pathlib import Path

import duckdb
import pyarrow as pa

from .schema import SCHEMAS


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def load_duckdb(dataset, database):
    dataset = Path(dataset).resolve()
    with duckdb.connect(str(database)) as connection:
        connection.execute("BEGIN")
        try:
            for name in SCHEMAS:
                connection.execute(f'CREATE OR REPLACE TABLE "{name}" AS SELECT * FROM read_parquet(?)',
                                   [str(dataset / (name + ".parquet"))])
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise


def clickhouse_ddl():
    statements = []
    for name, schema in SCHEMAS.items():
        columns = []
        for field in schema:
            typ = ("Bool" if pa.types.is_boolean(field.type) else
                   "Int64" if pa.types.is_integer(field.type) else
                   "Decimal(38, 18)" if pa.types.is_decimal(field.type) else "String")
            columns.append(f"`{field.name}` Nullable({typ})")
        statements.append(f"CREATE TABLE `{name}` ({', '.join(columns)}) ENGINE = MergeTree ORDER BY tuple();")
    return "\n".join(statements) + "\n"
