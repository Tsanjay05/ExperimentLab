import math
import json

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from experimentlab.analysis.analyzer import Analyzer
from experimentlab.analysis.guardrails import check_guardrail
from experimentlab.analysis.inference import (
    estimate_binary_effect,
    estimate_continuous_effect,
)
from experimentlab.analysis.randomization import check_sample_ratio_mismatch
from experimentlab.storage.database import connect, initialize_database


NOW = "2026-10-22T00:00:00Z"
EXPERIMENT_ID = "EXP-2026-000001"
CONTROL_ID = f"VAR-{EXPERIMENT_ID}-A"
TREATMENT_ID = f"VAR-{EXPERIMENT_ID}-B"
PRIMARY_METRIC_ID = "MET-000001"
GUARDRAIL_METRIC_ID = "MET-000002"


def test_binary_effect_matches_two_proportion_z_test_and_wald_interval():
    control = np.array([1] * 20 + [0] * 80, dtype=float)
    treatment = np.array([1] * 60 + [0] * 40, dtype=float)

    estimate = estimate_binary_effect(control, treatment)

    effect = 0.6 - 0.2
    standard_error = math.sqrt(0.2 * 0.8 / 100 + 0.6 * 0.4 / 100)
    pooled_se = math.sqrt(0.4 * 0.6 * (1 / 100 + 1 / 100))
    expected_p = 2 * stats.norm.sf(abs(effect / pooled_se))
    critical_value = stats.norm.ppf(0.975)
    assert estimate.effect_estimate == pytest.approx(effect)
    assert estimate.standard_error == pytest.approx(standard_error)
    assert estimate.ci_lower == pytest.approx(effect - critical_value * standard_error)
    assert estimate.ci_upper == pytest.approx(effect + critical_value * standard_error)
    assert estimate.p_value == pytest.approx(expected_p)
    assert estimate.control_n == estimate.treatment_n == 100
    assert estimate.inference_method == "pooled_two_proportion_z_wald"


@pytest.mark.parametrize(
    ("control", "treatment", "expected_effect", "expected_p"),
    [
        ([0] * 10, [0] * 10, 0.0, 1.0),
        ([1] * 10, [1] * 10, 0.0, 1.0),
        (
            [0] * 10,
            [1] * 10,
            1.0,
            stats.fisher_exact([[0, 10], [10, 0]]).pvalue,
        ),
    ],
)
def test_binary_degenerate_outcomes_use_exact_test_and_non_degenerate_interval(
    control, treatment, expected_effect, expected_p
):
    estimate = estimate_binary_effect(control, treatment)

    assert estimate.effect_estimate == pytest.approx(expected_effect)
    assert estimate.p_value == pytest.approx(expected_p)
    assert estimate.ci_lower < estimate.effect_estimate <= estimate.ci_upper
    assert estimate.ci_lower < estimate.ci_upper
    assert estimate.standard_error == pytest.approx(0.0)
    assert estimate.inference_method == "fisher_exact_newcombe_wilson"


@pytest.mark.parametrize(
    ("control", "treatment"),
    [
        ([], [0, 1]),
        ([0], [0, 1]),
        ([0, 1], []),
        ([0, np.nan], [0, 1]),
        ([0, np.inf], [0, 1]),
    ],
)
def test_binary_inference_rejects_empty_small_or_missing_samples(control, treatment):
    with pytest.raises(ValueError):
        estimate_binary_effect(control, treatment)


def test_binary_inference_rejects_non_binary_outcomes_and_invalid_confidence():
    with pytest.raises(ValueError, match="only 0 or 1"):
        estimate_binary_effect([0, 2], [0, 1])
    with pytest.raises(ValueError, match="confidence_level"):
        estimate_binary_effect([0, 1], [0, 1], confidence_level=1)
    with pytest.raises(ValueError, match="confidence_level"):
        estimate_binary_effect([0, 1], [0, 1], confidence_level="invalid")


def test_continuous_effect_uses_welch_test_and_confidence_interval():
    control = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    treatment = np.array([2.0, 4.0, 5.0, 6.0, 8.0])

    estimate = estimate_continuous_effect(control, treatment)
    reference = stats.ttest_ind(treatment, control, equal_var=False)

    assert estimate.p_value == pytest.approx(reference.pvalue)
    assert estimate.effect_estimate == pytest.approx(
        treatment.mean() - control.mean()
    )
    assert estimate.ci_lower < estimate.effect_estimate < estimate.ci_upper
    assert estimate.inference_method == "welch_t"


def test_continuous_zero_variance_groups_do_not_claim_certainty():
    with pytest.raises(ValueError, match="zero variance"):
        estimate_continuous_effect([2.0, 2.0], [3.0, 3.0])
    with pytest.raises(ValueError, match="zero variance"):
        estimate_continuous_effect([2.0, 2.0], [2.0, 2.0])


@pytest.mark.parametrize(
    ("control", "treatment"),
    [
        ([], [1, 2]),
        ([1], [1, 2]),
        ([1, 2], []),
        ([1, np.nan], [1, 2]),
        ([1, np.inf], [1, 2]),
    ],
)
def test_continuous_inference_rejects_empty_small_or_missing_samples(
    control, treatment
):
    with pytest.raises(ValueError):
        estimate_continuous_effect(control, treatment)


def test_continuous_inference_rejects_invalid_confidence_level():
    with pytest.raises(ValueError, match="confidence_level"):
        estimate_continuous_effect([1, 2], [2, 3], confidence_level=0)
    with pytest.raises(ValueError, match="confidence_level"):
        estimate_continuous_effect([1, 2], [2, 3], confidence_level="invalid")


def test_srm_detects_severe_allocation_imbalance_as_warning():
    result = check_sample_ratio_mismatch(
        {"A": 950, "B": 50},
        {"A": 0.5, "B": 0.5},
    )

    assert result.p_value < 0.001
    assert result.significant is True
    assert result.status == "warning"


def test_srm_accepts_counts_consistent_with_planned_allocation():
    result = check_sample_ratio_mismatch(
        {"A": 500, "B": 500},
        {"A": 0.5, "B": 0.5},
    )

    assert result.p_value == pytest.approx(1.0)
    assert result.significant is False
    assert result.status == "pass"


def test_guardrail_direction_and_regression_threshold():
    check = check_guardrail(
        guardrail_id="GRD-000001",
        metric_definition_id=GUARDRAIL_METRIC_ID,
        control_value=0.1,
        treatment_value=0.17,
        comparison_direction="lower_is_better",
        max_regression=0.05,
        severity="blocker",
    )

    assert check.regression == pytest.approx(0.07)
    assert check.exceeded


@pytest.mark.parametrize(
    ("control", "treatment", "max_regression"),
    [
        (float("nan"), 0.2, 0.1),
        (0.1, float("inf"), 0.1),
        (0.1, 0.2, float("nan")),
        (0.1, 0.2, -0.1),
    ],
)
def test_guardrail_rejects_non_finite_or_invalid_values(
    control, treatment, max_regression
):
    with pytest.raises(ValueError):
        check_guardrail(
            guardrail_id="GRD-000001",
            metric_definition_id=GUARDRAIL_METRIC_ID,
            control_value=control,
            treatment_value=treatment,
            comparison_direction="lower_is_better",
            max_regression=max_regression,
            severity="blocker",
        )


@pytest.fixture
def analysis_database(tmp_path):
    database_path = initialize_database(tmp_path / "analysis.db")
    with connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO experiments (
                experiment_id, name, hypothesis, status, start_at, end_at,
                created_at, updated_at
            ) VALUES (?, 'Analysis test', 'Treatment increases conversion',
                      'completed', ?, '2026-10-30T00:00:00Z', ?, ?)
            """,
            (
                EXPERIMENT_ID,
                NOW,
                NOW,
                NOW,
            ),
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
        for metric_id, key, name in (
            (PRIMARY_METRIC_ID, "conversion_rate", "Conversion rate"),
            (GUARDRAIL_METRIC_ID, "error_rate", "Error rate"),
        ):
            connection.execute(
                """
                INSERT INTO metric_definitions (
                    metric_definition_id, experiment_id, metric_key, version,
                    name, metric_type, unit, aggregation, denominator,
                    attribution_window_days, definition_json, content_hash,
                    created_at, effective_at
                ) VALUES (?, ?, ?, 1, ?, 'binary', 'proportion', 'proportion',
                          'assigned members', 7, '{}', ?, ?, ?)
                """,
                (metric_id, EXPERIMENT_ID, key, name, "a" * 64, NOW, NOW),
            )
        connection.execute(
            """
            UPDATE experiments
            SET primary_metric_definition_id = ?
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
            ) VALUES ('GRD-000001', ?, ?, 'lower_is_better', 0.1, 0.05,
                      'blocker', ?)
            """,
            (EXPERIMENT_ID, GUARDRAIL_METRIC_ID, NOW),
        )

        conversions = []
        conversion_number = 1
        for user_number in range(1, 41):
            user_id = f"USR-{user_number:06d}"
            variant_id = CONTROL_ID if user_number <= 20 else TREATMENT_ID
            connection.execute(
                """
                INSERT INTO audience_members (audience_member_id, created_at)
                VALUES (?, ?)
                """,
                (user_id, NOW),
            )
            assignment_id = f"ASG-{EXPERIMENT_ID}-{user_id}"
            connection.execute(
                """
                INSERT INTO assignments (
                    assignment_id, experiment_id, variant_id, audience_member_id,
                    assigned_at, assignment_probability, randomization_bucket
                ) VALUES (?, ?, ?, ?, ?, 0.5, ?)
                """,
                (
                    assignment_id,
                    EXPERIMENT_ID,
                    variant_id,
                    user_id,
                    NOW,
                    (user_number - 1) * 25_000,
                ),
            )
            primary_success = (
                user_number <= 8 or 21 <= user_number <= 32
            )
            guardrail_success = (
                9 <= user_number <= 10 or 33 <= user_number <= 38
            )
            for metric_id, succeeded in (
                (PRIMARY_METRIC_ID, primary_success),
                (GUARDRAIL_METRIC_ID, guardrail_success),
            ):
                if succeeded:
                    conversions.append(
                        (
                            f"CONV-2026-{conversion_number:06d}",
                            assignment_id,
                            EXPERIMENT_ID,
                            metric_id,
                            "2026-10-23T00:00:00Z",
                            1.0,
                            "synthetic_test",
                            "{}",
                        )
                    )
                    conversion_number += 1

        connection.executemany(
            """
            INSERT INTO conversion_events (
                conversion_event_id, assignment_id, experiment_id,
                metric_definition_id, occurred_at, value, source, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            conversions,
        )
    return database_path


def test_analyzer_persists_itt_result_with_diagnostics_and_snapshot(analysis_database):
    results = Analyzer(analysis_database).analyze(EXPERIMENT_ID)

    assert len(results) == 1
    result = results[0]
    assert result["metric_definition_id"] == PRIMARY_METRIC_ID
    assert result["metric_definition_version"] == 1
    assert result["effect_estimate"] == pytest.approx(0.2)
    assert result["control_n"] == result["treatment_n"] == 20
    assert result["srm_status"] == "pass"
    assert result["guardrail_status"] == "fail"
    assert result["decision"] == "do_not_ship"
    assert result["inference_method"] == "pooled_two_proportion_z_wald"
    assert len(result["input_snapshot_hash"]) == 64

    with connect(analysis_database) as connection:
        row = connection.execute(
            """
            SELECT metric_definition_id, metric_definition_version,
                   analysis_plan_version, analysis_method,
                   outcome_window_start, outcome_window_end, input_snapshot_hash,
                   analysis_config_json
            FROM experiment_results WHERE result_id = ?
            """,
            (result["result_id"],),
        ).fetchone()
        assert row["metric_definition_id"] == PRIMARY_METRIC_ID
        assert row["metric_definition_version"] == 1
        assert row["analysis_plan_version"] == "itt-v1"
        assert row["analysis_method"] == "intention_to_treat"
        assert row["outcome_window_end"] > row["outcome_window_start"]
        assert row["input_snapshot_hash"] == result["input_snapshot_hash"]
        assert json.loads(row["analysis_config_json"])["inference_method"] == (
            "pooled_two_proportion_z_wald"
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_analyzer_reports_deterministic_guardrail_regression(analysis_database):
    result = Analyzer(analysis_database).analyze(EXPERIMENT_ID)[0]

    assert result["guardrail_status"] == "fail"
    assert result["decision"] == "do_not_ship"
    with connect(analysis_database) as connection:
        row = connection.execute(
            """
            SELECT analysis_config_json
            FROM experiment_results
            WHERE result_id = ?
            """,
            (result["result_id"],),
        ).fetchone()
    diagnostics = json.loads(row["analysis_config_json"])["guardrails"]
    assert diagnostics == [
        {
            "control_value": 0.1,
            "exceeded": True,
            "guardrail_id": "GRD-000001",
            "max_regression": 0.05,
            "metric_definition_id": GUARDRAIL_METRIC_ID,
            "regression": pytest.approx(0.2),
            "severity": "blocker",
            "treatment_value": 0.3,
        }
    ]


@pytest.mark.parametrize(
    "assignment_rows",
    [
        [{"assignment_id": "control-1", "variant_id": CONTROL_ID, "assigned_at": NOW}],
        [],
    ],
)
def test_analyzer_rejects_guardrail_with_small_or_empty_groups(
    analysis_database, assignment_rows
):
    with connect(analysis_database) as connection:
        guardrails = pd.read_sql_query(
            "SELECT guardrail_id, metric_definition_id, comparison_direction, "
            "max_regression, severity, version, metric_key, metric_type, unit, "
            "aggregation, denominator, attribution_window_days, definition_json, "
            "content_hash FROM guardrail_metrics JOIN metric_definitions "
            "USING (metric_definition_id) WHERE guardrail_id = 'GRD-000001'",
            connection,
        )

    assignments = pd.DataFrame(
        assignment_rows,
        columns=["assignment_id", "variant_id", "assigned_at"],
    )
    with pytest.raises(ValueError, match="requires at least two"):
        Analyzer(analysis_database)._evaluate_guardrails(
            assignments,
            pd.DataFrame(
                columns=[
                    "conversion_event_id",
                    "assignment_id",
                    "metric_definition_id",
                    "occurred_at",
                    "value",
                ]
            ),
            guardrails,
            CONTROL_ID,
            TREATMENT_ID,
        )


def test_analyzer_appends_results_instead_of_overwriting(analysis_database):
    analyzer = Analyzer(analysis_database)

    first = analyzer.analyze(EXPERIMENT_ID, analysis_plan_version="itt-v1")
    second = analyzer.analyze(EXPERIMENT_ID, analysis_plan_version="itt-v2")

    assert first[0]["result_id"] != second[0]["result_id"]
    with connect(analysis_database) as connection:
        rows = connection.execute(
            """
            SELECT result_id, analysis_plan_version
            FROM experiment_results ORDER BY result_id
            """
        ).fetchall()
    assert [(row["result_id"], row["analysis_plan_version"]) for row in rows] == [
        ("RES-000001", "itt-v1"),
        ("RES-000002", "itt-v2"),
    ]


def test_analyzer_rejects_invalid_confidence_without_persisting_result(
    analysis_database,
):
    with pytest.raises(ValueError, match="confidence_level"):
        Analyzer(analysis_database).analyze(
            EXPERIMENT_ID,
            confidence_level="invalid",
        )

    with connect(analysis_database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM experiment_results"
        ).fetchone()[0] == 0
