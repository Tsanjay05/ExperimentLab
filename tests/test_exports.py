import csv
import json
import sqlite3

import pandas as pd
import pytest

from experimentlab.exports.export import (
    CLEAN_DATA_TABLES,
    export_clean_dataset,
    export_clean_dataset_sql,
    export_experiment_results,
)
from experimentlab.storage.database import connect, initialize_database


NOW = "2026-10-22T00:00:00Z"
EXPERIMENT_ID = "EXP-2026-000001"
CONTROL_ID = f"VAR-{EXPERIMENT_ID}-A"
TREATMENT_ID = f"VAR-{EXPERIMENT_ID}-B"
PRIMARY_METRIC_ID = "MET-000001"


@pytest.fixture
def export_database(tmp_path):
    database_path = initialize_database(tmp_path / "test.db")
    with connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO experiments (
                experiment_id, name, hypothesis, status, start_at, end_at,
                created_at, updated_at
            ) VALUES (?, 'Export test', 'Treatment improves conversion',
                      'completed', ?, '2026-10-30T00:00:00Z', ?, ?)
            """,
            (EXPERIMENT_ID, NOW, NOW, NOW),
        )
        for variant_id, key, label, is_control in (
            (CONTROL_ID, "A", "Control", 1),
            (TREATMENT_ID, "B", "Treatment", 0),
        ):
            connection.execute(
                """
                INSERT INTO variants (
                    variant_id, experiment_id, variant_key, display_name,
                    is_control, allocation_probability, status
                ) VALUES (?, ?, ?, ?, ?, 0.5, 'active')
                """,
                (variant_id, EXPERIMENT_ID, key, label, is_control),
            )
        connection.execute(
            """
            INSERT INTO metric_definitions (
                metric_definition_id, experiment_id, metric_key, version,
                name, metric_type, unit, aggregation, denominator,
                attribution_window_days, definition_json, content_hash,
                created_at, effective_at
            ) VALUES (?, ?, 'conversion_rate', 1, 'Conversion rate', 'binary',
                      'proportion', 'proportion', 'assigned members', 7, '{}',
                      ?, ?, ?)
            """,
            (PRIMARY_METRIC_ID, EXPERIMENT_ID, "a" * 64, NOW, NOW),
        )
        connection.execute(
            """
            UPDATE experiments SET primary_metric_definition_id = ?
            WHERE experiment_id = ?
            """,
            (PRIMARY_METRIC_ID, EXPERIMENT_ID),
        )
        connection.execute(
            """
            INSERT INTO guardrail_metrics (
                guardrail_id, experiment_id, metric_definition_id,
                comparison_direction, threshold, max_regression, severity,
                created_at
            ) VALUES ('GRD-000001', ?, ?, 'lower_is_better', 0.1, 0.02,
                      'warning', ?)
            """,
            (EXPERIMENT_ID, PRIMARY_METRIC_ID, NOW),
        )
        connection.execute(
            """
            INSERT INTO audience_members (audience_member_id, created_at, country)
            VALUES ('USR-000001', ?, 'US')
            """,
            (NOW,),
        )
        assignment_id = f"ASG-{EXPERIMENT_ID}-USR-000001"
        connection.execute(
            """
            INSERT INTO assignments (
                assignment_id, experiment_id, variant_id, audience_member_id,
                assigned_at, assignment_probability, randomization_bucket
            ) VALUES (?, ?, ?, 'USR-000001', ?, 0.5, 100000)
            """,
            (assignment_id, EXPERIMENT_ID, CONTROL_ID, NOW),
        )
        connection.execute(
            """
            INSERT INTO exposure_events (
                exposure_event_id, assignment_id, experiment_id, occurred_at,
                event_type, source
            ) VALUES ('EXPOS-2026-000001', ?, ?, '2026-10-22T01:00:00Z',
                      'client_render', 'test')
            """,
            (assignment_id, EXPERIMENT_ID),
        )
        connection.execute(
            """
            INSERT INTO conversion_events (
                conversion_event_id, assignment_id, experiment_id,
                metric_definition_id, occurred_at, value, source
            ) VALUES ('CONV-2026-000001', ?, ?, ?, '2026-10-23T00:00:00Z',
                      1.0, 'test')
            """,
            (assignment_id, EXPERIMENT_ID, PRIMARY_METRIC_ID),
        )
        connection.execute(
            """
            INSERT INTO experiment_results (
                result_id, experiment_id, metric_definition_id,
                metric_definition_version, control_variant_id,
                treatment_variant_id, computed_at, analysis_plan_version,
                outcome_window_start, outcome_window_end, control_n, treatment_n,
                effect_estimate, standard_error, confidence_level, ci_lower,
                ci_upper, p_value, srm_p_value, srm_status, guardrail_status,
                decision, analysis_method, analysis_config_json,
                input_snapshot_hash
            ) VALUES (
                'RES-000001', ?, ?, 1, ?, ?, ?, 'itt-v1', ?, ?, 1, 1, 0.1,
                0.05, 0.95, 0.002, 0.198, 0.04, 0.8, 'pass', 'pass', 'ship',
                'intention_to_treat', '{}', ?
            )
            """,
            (
                EXPERIMENT_ID,
                PRIMARY_METRIC_ID,
                CONTROL_ID,
                TREATMENT_ID,
                NOW,
                NOW,
                "2026-10-29T00:00:00Z",
                "b" * 64,
            ),
        )
    return database_path


def test_clean_analytical_tables_export_to_csv_and_json(export_database, tmp_path):
    output_directory = tmp_path / "exports"

    exported = export_clean_dataset(export_database, output_directory)

    assert set(exported) == set(CLEAN_DATA_TABLES)
    for table_name, formats in exported.items():
        assert set(formats) == {"csv", "json"}
        csv_path = formats["csv"]
        json_path = formats["json"]
        assert csv_path.exists()
        assert json_path.exists()

        with csv_path.open(encoding="utf-8", newline="") as file:
            csv_rows = list(csv.DictReader(file))
        json_rows = json.loads(json_path.read_text(encoding="utf-8"))
        assert len(csv_rows) == len(json_rows)
        assert csv_rows == [
            {key: "" if value is None else str(value) for key, value in row.items()}
            for row in json_rows
        ]

    assert "experiment_results" not in exported
    assert not list(output_directory.glob("*ground_truth*"))
    assert not list(output_directory.glob("*scenario*"))


def test_results_export_contains_saved_result_rows(export_database, tmp_path):
    exported = export_experiment_results(export_database, tmp_path / "results")

    assert set(exported) == {"csv", "json"}
    csv_frame = pd.read_csv(exported["csv"])
    json_rows = json.loads(exported["json"].read_text(encoding="utf-8"))
    assert len(csv_frame) == len(json_rows) == 1
    assert csv_frame.loc[0, "result_id"] == "RES-000001"
    assert json_rows[0]["metric_definition_id"] == PRIMARY_METRIC_ID
    assert json_rows[0]["analysis_method"] == "intention_to_treat"


def test_clean_sql_export_round_trips_schema_and_clean_data(export_database, tmp_path):
    sql_path = export_clean_dataset_sql(
        export_database,
        tmp_path / "sql-export" / "clean_dataset.sql",
    )
    imported_path = tmp_path / "round_trip.db"

    imported = sqlite3.connect(imported_path)
    try:
        imported.executescript(sql_path.read_text(encoding="utf-8"))
    finally:
        imported.close()

    with connect(export_database) as source, connect(imported_path) as restored:
        for table_name in CLEAN_DATA_TABLES:
            source_count = source.execute(
                f'SELECT COUNT(*) FROM "{table_name}"'
            ).fetchone()[0]
            restored_count = restored.execute(
                f'SELECT COUNT(*) FROM "{table_name}"'
            ).fetchone()[0]
            assert restored_count == source_count

        assert restored.execute(
            "SELECT COUNT(*) FROM experiment_results"
        ).fetchone()[0] == 0
        assert restored.execute(
            "SELECT experiment_id, primary_metric_definition_id FROM experiments"
        ).fetchone()[:] == (EXPERIMENT_ID, PRIMARY_METRIC_ID)
        assert restored.execute(
            "SELECT currency FROM conversion_events"
        ).fetchone()[0] is None
        assert restored.execute("PRAGMA foreign_key_check").fetchall() == []
        assert restored.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    sql_text = sql_path.read_text(encoding="utf-8")
    assert "RES-000001" not in sql_text
    assert "ground_truth" not in sql_text
    assert "scenario" not in sql_text.lower()


def test_export_fails_explicitly_for_missing_tables(tmp_path):
    database_path = initialize_database(tmp_path / "incomplete.db")
    with connect(database_path) as connection:
        connection.execute("DROP TABLE experiments")

    with pytest.raises(ValueError, match="missing required table: experiments"):
        export_clean_dataset(database_path, tmp_path / "exports")
