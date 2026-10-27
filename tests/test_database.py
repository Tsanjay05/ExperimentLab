import sqlite3

import pytest

from experimentlab.storage.database import connect, initialize_database


ENTITY_TABLES = {
    "experiments",
    "variants",
    "audience_members",
    "assignments",
    "exposure_events",
    "conversion_events",
    "metric_definitions",
    "guardrail_metrics",
    "experiment_results",
}

NOW = "2026-10-22T00:00:00Z"


@pytest.fixture
def database(tmp_path):
    path = initialize_database(tmp_path / "generated" / "test.db")
    return path


def insert_experiment(connection, experiment_id="EXP-2026-000001"):
    connection.execute(
        """
        INSERT INTO experiments
            (experiment_id, name, hypothesis, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (experiment_id, f"Experiment {experiment_id}", "A test hypothesis", NOW, NOW),
    )


def insert_metric(connection, metric_id, experiment_id):
    connection.execute(
        """
        INSERT INTO metric_definitions (
            metric_definition_id, experiment_id, metric_key, version, name,
            metric_type, unit, aggregation, attribution_window_days,
            definition_json, content_hash, created_at, effective_at
        ) VALUES (?, ?, 'conversion', 1, 'Conversion rate', 'binary', 'rate',
                  'proportion', 7, '{}', ?, ?, ?)
        """,
        (metric_id, experiment_id, "a" * 64, NOW, NOW),
    )


def test_initialization_creates_all_nine_entity_tables(database):
    with connect(database) as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert ENTITY_TABLES <= tables


def test_foreign_keys_are_enabled_on_each_connection(database):
    with connect(database) as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    with connect(database) as second_connection:
        assert second_connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_primary_key_and_uniqueness_constraints(database):
    with connect(database) as connection:
        insert_experiment(connection)

        with pytest.raises(sqlite3.IntegrityError):
            insert_experiment(connection)

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO experiments
                    (experiment_id, name, hypothesis, created_at, updated_at)
                VALUES ('EXP-2026-000002', 'Experiment EXP-2026-000001',
                        'Another hypothesis', ?, ?)
                """,
                (NOW, NOW),
            )

        connection.execute(
            """
            INSERT INTO variants (
                variant_id, experiment_id, variant_key, display_name,
                is_control, allocation_probability
            ) VALUES ('VAR-EXP-2026-000001-A', 'EXP-2026-000001',
                      'A', 'Control', 1, 0.5)
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO variants (
                    variant_id, experiment_id, variant_key, display_name,
                    is_control, allocation_probability
                ) VALUES ('VAR-EXP-2026-000001-B', 'EXP-2026-000001',
                          'A', 'Duplicate key', 0, 0.5)
                """
            )


def test_invalid_and_cross_experiment_references_are_rejected(database):
    with connect(database) as connection:
        insert_experiment(connection, "EXP-2026-000001")
        insert_experiment(connection, "EXP-2026-000002")
        insert_metric(connection, "MET-000001", "EXP-2026-000001")

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO variants (
                    variant_id, experiment_id, variant_key, display_name,
                    is_control, allocation_probability
                ) VALUES ('VAR-EXP-2026-000001-A', 'EXP-2026-999999',
                          'A', 'Missing experiment', 1, 1.0)
                """
            )

        connection.execute(
            """
            INSERT INTO variants (
                variant_id, experiment_id, variant_key, display_name,
                is_control, allocation_probability
            ) VALUES ('VAR-EXP-2026-000001-A', 'EXP-2026-000001',
                      'A', 'Control', 1, 0.5)
            """
        )
        connection.execute(
            """
            INSERT INTO audience_members (audience_member_id, created_at)
            VALUES ('USR-000001', ?)
            """,
            (NOW,),
        )

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO assignments (
                    assignment_id, experiment_id, variant_id, audience_member_id,
                    assigned_at, assignment_probability, randomization_bucket
                ) VALUES (
                    'ASG-EXP-2026-000002-USR-000001', 'EXP-2026-000002',
                    'VAR-EXP-2026-000001-A', 'USR-000001', ?, 0.5, 1
                )
                """,
                (NOW,),
            )

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO guardrail_metrics (
                    guardrail_id, experiment_id, metric_definition_id,
                    comparison_direction, threshold, max_regression, severity,
                    created_at
                ) VALUES (
                    'GRD-000001', 'EXP-2026-000002', 'MET-000001',
                    'higher_is_better', 0.1, 0.02, 'warning', ?
                )
                """,
                (NOW,),
            )
