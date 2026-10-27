"""CSV and JSON exports for clean analytical inputs and persisted results."""

from contextlib import closing
import math
from pathlib import Path
import sqlite3

import pandas as pd

from experimentlab.config import DEFAULT_DATABASE_PATH, PROJECT_ROOT, SCHEMA_PATH
from experimentlab.storage.database import connect

DEFAULT_EXPORT_DIRECTORY = PROJECT_ROOT / "data" / "exports"

CLEAN_DATA_TABLES = (
    "experiments",
    "variants",
    "audience_members",
    "assignments",
    "exposure_events",
    "conversion_events",
    "metric_definitions",
    "guardrail_metrics",
)

TABLE_PRIMARY_KEYS = {
    "experiments": "experiment_id",
    "variants": "variant_id",
    "audience_members": "audience_member_id",
    "assignments": "assignment_id",
    "exposure_events": "exposure_event_id",
    "conversion_events": "conversion_event_id",
    "metric_definitions": "metric_definition_id",
    "guardrail_metrics": "guardrail_id",
    "experiment_results": "result_id",
}

SQL_SEED_TABLES = (
    "experiments",
    "audience_members",
    "variants",
    "metric_definitions",
    "guardrail_metrics",
    "assignments",
    "exposure_events",
    "conversion_events",
)


def _read_table(database_path: str | Path, table_name: str) -> pd.DataFrame:
    if table_name not in TABLE_PRIMARY_KEYS:
        raise ValueError(f"unsupported export table: {table_name}")

    with closing(connect(database_path)) as connection:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        if exists is None:
            raise ValueError(f"database is missing required table: {table_name}")
        return pd.read_sql_query(
            f'SELECT * FROM "{table_name}" ORDER BY "{TABLE_PRIMARY_KEYS[table_name]}"',
            connection,
        )


def _sql_literal(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("SQL seed export cannot serialize non-finite numbers")
        return repr(value)
    if isinstance(value, bytes):
        return f"X'{value.hex()}'"
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    raise TypeError(f"unsupported SQLite value type: {type(value).__name__}")


def export_clean_dataset_sql(
    database_path: str | Path = DEFAULT_DATABASE_PATH,
    output_path: str | Path = DEFAULT_EXPORT_DIRECTORY / "clean_dataset.sql",
) -> Path:
    """Export the schema and clean analytical inputs as an importable SQL script.

    Experiment results, ground-truth labels, and scenario fixtures are excluded.
    The result table remains in the schema and can be populated separately using
    the existing experiment-result export.
    """
    table_statements: list[str] = []
    primary_metric_updates: list[str] = []

    with closing(connect(database_path)) as connection:
        for table_name in SQL_SEED_TABLES:
            if connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table_name,),
            ).fetchone() is None:
                raise ValueError(f"database is missing required table: {table_name}")

            primary_key = TABLE_PRIMARY_KEYS[table_name]
            cursor = connection.execute(
                f'SELECT * FROM "{table_name}" ORDER BY "{primary_key}"'
            )
            columns = [column[0] for column in cursor.description]
            quoted_columns = ", ".join(f'"{column}"' for column in columns)
            for record in cursor:
                values = list(record)
                if table_name == "experiments":
                    metric_index = columns.index("primary_metric_definition_id")
                    metric_id = values[metric_index]
                    values[metric_index] = None
                    if metric_id is not None:
                        primary_metric_updates.append(
                            "UPDATE experiments SET primary_metric_definition_id = "
                            f"{_sql_literal(metric_id)} WHERE experiment_id = "
                            f"{_sql_literal(values[columns.index('experiment_id')])};"
                        )
                literal_values = ", ".join(_sql_literal(value) for value in values)
                table_statements.append(
                    f'INSERT INTO "{table_name}" ({quoted_columns}) '
                    f"VALUES ({literal_values});"
                )

    schema = SCHEMA_PATH.read_text(encoding="utf-8").rstrip()
    script = "\n".join(
        [
            schema,
            "",
            "BEGIN TRANSACTION;",
            *table_statements,
            *primary_metric_updates,
            "COMMIT;",
            "",
        ]
    )
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(script, encoding="utf-8", newline="\n")
    return destination


def _write_formats(
    frame: pd.DataFrame,
    output_directory: Path,
    base_name: str,
) -> dict[str, Path]:
    output_directory.mkdir(parents=True, exist_ok=True)
    csv_path = output_directory / f"{base_name}.csv"
    json_path = output_directory / f"{base_name}.json"

    frame.to_csv(csv_path, index=False, lineterminator="\n")
    json_path.write_text(
        frame.to_json(
            orient="records",
            indent=2,
            force_ascii=False,
            double_precision=15,
        )
        + "\n",
        encoding="utf-8",
    )
    return {"csv": csv_path, "json": json_path}


def export_clean_dataset(
    database_path: str | Path = DEFAULT_DATABASE_PATH,
    output_directory: str | Path = DEFAULT_EXPORT_DIRECTORY,
) -> dict[str, dict[str, Path]]:
    """Export all clean analytical input tables separately as CSV and JSON.

    Scenario fixtures and ground-truth labels are intentionally excluded.
    """
    output_path = Path(output_directory)
    exported = {}
    for table_name in CLEAN_DATA_TABLES:
        frame = _read_table(database_path, table_name)
        exported[table_name] = _write_formats(
            frame,
            output_path,
            f"clean_{table_name}",
        )
    return exported


def export_experiment_results(
    database_path: str | Path = DEFAULT_DATABASE_PATH,
    output_directory: str | Path = DEFAULT_EXPORT_DIRECTORY,
) -> dict[str, Path]:
    """Export persisted experiment results as CSV and JSON."""
    frame = _read_table(database_path, "experiment_results")
    return _write_formats(
        frame,
        Path(output_directory),
        "experiment_results",
    )
