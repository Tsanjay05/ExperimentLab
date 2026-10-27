"""Executable validation for deliberately invalid scenario fixtures."""

from copy import deepcopy
import sqlite3
from pathlib import Path
from typing import Any

from experimentlab.analysis.randomization import check_sample_ratio_mismatch
from experimentlab.config import SCHEMA_PATH
from experimentlab.storage.database import connect


def _validate_multiple_assignment(
    connection: sqlite3.Connection,
    anomaly: dict[str, Any],
) -> tuple[bool, str]:
    existing = connection.execute(
        """
        SELECT assignment_id, variant_id
        FROM assignments
        WHERE experiment_id = ? AND audience_member_id = ?
        """,
        (anomaly["experiment_id"], anomaly["audience_member_id"]),
    ).fetchone()
    detected = (
        existing is not None
        and existing["assignment_id"] == anomaly["existing_assignment_id"]
        and existing["variant_id"] == anomaly["existing_variant_id"]
        and anomaly["attempted_assignment_id"] != existing["assignment_id"]
        and anomaly["attempted_variant_id"] != existing["variant_id"]
    )
    if detected:
        return True, "second variant assignment rejected by the one-assignment rule"
    return False, "scenario did not establish a conflicting second assignment"


def _validate_early_exposure(
    connection: sqlite3.Connection,
    anomaly: dict[str, Any],
) -> tuple[bool, str]:
    next_number = connection.execute(
        """
        SELECT COALESCE(MAX(CAST(substr(exposure_event_id, 12) AS INTEGER)), 0) + 1
        FROM exposure_events
        """
    ).fetchone()[0]
    connection.execute("SAVEPOINT scenario_exposure")
    try:
        connection.execute(
            """
            INSERT INTO exposure_events (
                exposure_event_id, assignment_id, experiment_id, occurred_at,
                event_type, source, payload_json
            ) VALUES (?, ?, ?, ?, 'client_render', 'scenario_validation', '{}')
            """,
            (
                f"EXPOS-2026-{next_number:06d}",
                anomaly["assignment_id"],
                anomaly["experiment_id"],
                anomaly["exposure_at"],
            ),
        )
    except sqlite3.IntegrityError as error:
        connection.execute("ROLLBACK TO scenario_exposure")
        connection.execute("RELEASE scenario_exposure")
        if "exposure cannot precede assignment" in str(error):
            return True, "SQLite rejected the exposure-before-assignment event"
        return False, f"event rejected for an unexpected constraint: {error}"
    else:
        connection.execute("ROLLBACK TO scenario_exposure")
        connection.execute("RELEASE scenario_exposure")
        return False, "SQLite accepted the exposure-before-assignment event"


def _validate_outcome_window(
    connection: sqlite3.Connection,
    anomaly: dict[str, Any],
) -> tuple[bool, str]:
    metric = connection.execute(
        """
        SELECT attribution_window_days
        FROM metric_definitions
        WHERE metric_definition_id = ?
        """,
        (anomaly["metric_definition_id"],),
    ).fetchone()
    defined_days = (
        None if metric is None else int(metric["attribution_window_days"])
    )
    declared_days = int(anomaly["fixture_analysis_window_days"])
    detected = defined_days is not None and declared_days != defined_days
    if detected:
        return (
            True,
            f"declared {declared_days}-day window conflicts with "
            f"metric definition ({defined_days} days)",
        )
    return False, "scenario outcome window matches the metric or metric is missing"


def _validate_ignored_srm(anomaly: dict[str, Any]) -> tuple[bool, str]:
    diagnostic = check_sample_ratio_mismatch(
        anomaly["fixture_observed_counts"],
        anomaly["planned_allocation"],
    )
    ignored = bool(anomaly["diagnostic_ignored"])
    detected = diagnostic.significant and diagnostic.status == "warning" and ignored
    if detected:
        return (
            True,
            f"SRM warning ignored despite p={diagnostic.p_value:.6g}; "
            "scenario validation reports failure",
        )
    return (
        False,
        f"expected ignored significant SRM warning; observed "
        f"status={diagnostic.status}, p={diagnostic.p_value:.6g}",
    )


def _validate_metric_version_history() -> tuple[bool, str]:
    connection = connect(":memory:")
    try:
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        experiment_id = "EXP-2026-000001"
        metric_id = "MET-000001"
        control_id = f"VAR-{experiment_id}-A"
        treatment_id = f"VAR-{experiment_id}-B"
        timestamp = "2026-10-22T00:00:00Z"
        connection.execute(
            """
            INSERT INTO experiments (
                experiment_id, name, hypothesis, status, created_at, updated_at
            ) VALUES (?, 'Scenario version history', 'Preserve historical metric',
                      'analyzed', ?, ?)
            """,
            (experiment_id, timestamp, timestamp),
        )
        for variant_id, key, control in (
            (control_id, "A", 1),
            (treatment_id, "B", 0),
        ):
            connection.execute(
                """
                INSERT INTO variants (
                    variant_id, experiment_id, variant_key, display_name,
                    is_control, allocation_probability, status
                ) VALUES (?, ?, ?, ?, ?, 0.5, 'active')
                """,
                (variant_id, experiment_id, key, key, control),
            )
        metric_values = (
            metric_id,
            experiment_id,
            "conversion_rate",
            "Conversion rate",
        )
        connection.execute(
            """
            INSERT INTO metric_definitions (
                metric_definition_id, experiment_id, metric_key, version, name,
                metric_type, unit, aggregation, attribution_window_days,
                definition_json, content_hash, created_at, effective_at
            ) VALUES (?, ?, ?, 1, ?, 'binary', 'proportion', 'proportion', 7,
                      '{"attribution_window_days":7}', ?, ?, ?)
            """,
            (*metric_values, "a" * 64, timestamp, timestamp),
        )
        connection.execute(
            """
            UPDATE experiments SET primary_metric_definition_id = ?
            WHERE experiment_id = ?
            """,
            (metric_id, experiment_id),
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
                'RES-000001', ?, ?, 1, ?, ?, ?, 'itt-v1', ?, ?, 0, 0,
                0.0, 0.0, 0.95, 0.0, 0.0, 1.0, 1.0, 'pass', 'pass',
                'inconclusive', 'intention_to_treat', '{}', ?
            )
            """,
            (
                experiment_id,
                metric_id,
                control_id,
                treatment_id,
                timestamp,
                timestamp,
                "2026-10-29T00:00:00Z",
                "a" * 64,
            ),
        )
        connection.execute(
            """
            INSERT INTO metric_definitions (
                metric_definition_id, experiment_id, metric_key, version, name,
                metric_type, unit, aggregation, attribution_window_days,
                definition_json, content_hash, created_at, effective_at
            ) VALUES (
                'MET-000002', ?, 'conversion_rate', 2, 'Conversion rate v2',
                'binary', 'proportion', 'proportion', 14,
                '{"attribution_window_days":14}', ?, ?, '2026-11-01T00:00:00Z'
            )
            """,
            (experiment_id, "b" * 64, timestamp),
        )
        historical = connection.execute(
            """
            SELECT result.metric_definition_id, result.metric_definition_version,
                   metric.version AS referenced_version
            FROM experiment_results AS result
            JOIN metric_definitions AS metric
              ON metric.metric_definition_id = result.metric_definition_id
            WHERE result.result_id = 'RES-000001'
            """
        ).fetchone()
        later_definition = connection.execute(
            """
            SELECT version, attribution_window_days, effective_at
            FROM metric_definitions
            WHERE metric_definition_id = 'MET-000002'
            """
        ).fetchone()
        detected = (
            historical is not None
            and historical["metric_definition_id"] == metric_id
            and historical["metric_definition_version"] == 1
            and historical["referenced_version"] == 1
            and later_definition is not None
            and later_definition["version"] == 2
            and later_definition["attribution_window_days"] == 14
            and later_definition["effective_at"] > timestamp
            and connection.execute(
                "SELECT COUNT(*) FROM metric_definitions WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()[0]
            == 2
        )
        if detected:
            return True, "v1 result remains bound to metric v1 after v2 insertion"
        return False, "historical result did not remain associated with metric v1"
    finally:
        connection.close()


def validate_scenario_fixtures(
    database_path: str | Path,
    scenarios: dict[str, Any],
) -> dict[str, Any]:
    """Execute every anomaly fixture against validators or SQLite constraints."""
    validated = deepcopy(scenarios)
    with connect(database_path) as connection:
        for fixture in validated["fixtures"]:
            issue_type = fixture["issue_type"]
            anomaly = fixture["anomaly"]
            if issue_type == "multiple_variant_assignments":
                detected, outcome = _validate_multiple_assignment(connection, anomaly)
            elif issue_type == "exposure_before_assignment":
                detected, outcome = _validate_early_exposure(connection, anomaly)
            elif issue_type == "inconsistent_outcome_window":
                detected, outcome = _validate_outcome_window(connection, anomaly)
            elif issue_type == "ignored_sample_ratio_mismatch":
                detected, outcome = _validate_ignored_srm(anomaly)
            elif issue_type == "metric_definition_changed_after_results":
                detected, outcome = _validate_metric_version_history()
            else:
                raise ValueError(f"unsupported scenario issue_type: {issue_type}")

            fixture["observed_outcome"] = outcome
            fixture["validation_passed"] = detected
    failed = [
        fixture["scenario_id"]
        for fixture in validated["fixtures"]
        if not fixture["validation_passed"]
    ]
    if failed:
        raise RuntimeError(f"scenario validation failed to detect: {failed}")
    return validated
