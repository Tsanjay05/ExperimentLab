"""SQLite-backed intention-to-treat analysis pipeline."""

from datetime import datetime, timezone
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from experimentlab.config import DEFAULT_DATABASE_PATH
from experimentlab.analysis.guardrails import (
    GuardrailCheck,
    check_guardrail,
    guardrail_diagnostics,
    summarize_guardrails,
)
from experimentlab.analysis.inference import (
    EffectEstimate,
    estimate_binary_effect,
    estimate_continuous_effect,
)
from experimentlab.analysis.randomization import check_sample_ratio_mismatch
from experimentlab.storage.database import connect


ANALYSIS_METHOD = "intention_to_treat"
DEFAULT_ANALYSIS_PLAN_VERSION = "itt-v1"


class Analyzer:
    """Load clean experiment inputs, analyze them, and append immutable results."""

    def __init__(self, database_path: str | Path | None = None) -> None:
        self.database_path = database_path or DEFAULT_DATABASE_PATH

    def analyze(
        self,
        experiment_id: str,
        *,
        confidence_level: float = 0.95,
        analysis_plan_version: str = DEFAULT_ANALYSIS_PLAN_VERSION,
    ) -> list[dict[str, Any]]:
        """Analyze each treatment variant against control and persist results."""
        try:
            confidence_level = float(confidence_level)
        except (TypeError, ValueError) as error:
            raise ValueError("confidence_level must be numeric") from error
        if not np.isfinite(confidence_level) or not 0 < confidence_level < 1:
            raise ValueError("confidence_level must be between zero and one")
        if (
            not isinstance(analysis_plan_version, str)
            or not analysis_plan_version.strip()
        ):
            raise ValueError("analysis_plan_version must be non-empty")

        with closing(connect(self.database_path)) as connection:
            inputs = self._load_inputs(connection, experiment_id)
            experiment = inputs["experiment"].iloc[0]
            variants = inputs["variants"]
            assignments = inputs["assignments"]
            metric = inputs["primary_metric"].iloc[0]
            guardrails = inputs["guardrails"]

            control_variants = variants.loc[variants["is_control"] == 1]
            if len(control_variants) != 1:
                raise ValueError(
                    f"{experiment_id} must have exactly one control variant"
                )
            control = control_variants.iloc[0]
            treatment_variants = variants.loc[variants["is_control"] == 0]
            if treatment_variants.empty:
                raise ValueError(f"{experiment_id} has no treatment variants")

            observed_counts = {
                row["variant_id"]: int(row["assignment_count"])
                for _, row in (
                    assignments.groupby("variant_id", as_index=False)
                    .size()
                    .rename(columns={"size": "assignment_count"})
                ).iterrows()
            }
            planned_allocation = {
                row["variant_id"]: float(row["allocation_probability"])
                for _, row in variants.iterrows()
            }
            for variant_id in planned_allocation:
                observed_counts.setdefault(variant_id, 0)
            srm = check_sample_ratio_mismatch(
                observed_counts,
                planned_allocation,
            )

            snapshot_hash = self._snapshot_hash(inputs)
            window_start = pd.to_datetime(assignments["assigned_at"], utc=True).min()
            max_assignment = pd.to_datetime(assignments["assigned_at"], utc=True).max()
            outcome_window_end = max_assignment + pd.Timedelta(
                days=int(metric["attribution_window_days"])
            )
            window_start_text = window_start.strftime("%Y-%m-%dT%H:%M:%SZ")
            window_end_text = outcome_window_end.strftime("%Y-%m-%dT%H:%M:%SZ")
            computed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            next_result_number = self._next_result_number(connection)
            results: list[dict[str, Any]] = []
            result_records: list[tuple[Any, ...]] = []

            for treatment in treatment_variants.to_dict(orient="records"):
                primary_outcomes = self._outcomes_for_metric(
                    assignments,
                    inputs["conversions"],
                    metric,
                )
                control_values = primary_outcomes.loc[
                    primary_outcomes["variant_id"] == control["variant_id"],
                    "outcome",
                ].to_numpy(dtype=float)
                treatment_values = primary_outcomes.loc[
                    primary_outcomes["variant_id"] == treatment["variant_id"],
                    "outcome",
                ].to_numpy(dtype=float)
                estimate = self._estimate(metric["metric_type"], control_values, treatment_values, confidence_level)

                checks = self._evaluate_guardrails(
                    assignments,
                    inputs["conversions"],
                    guardrails,
                    control["variant_id"],
                    treatment["variant_id"],
                )
                guardrail_status = summarize_guardrails(checks)
                decision = self._decision(estimate, guardrail_status)
                result_id = f"RES-{next_result_number:06d}"
                next_result_number += 1
                analysis_config = {
                    "method": ANALYSIS_METHOD,
                    "inference_method": estimate.inference_method,
                    "confidence_level": confidence_level,
                    "srm": {
                        "statistic": srm.statistic,
                        "p_value": srm.p_value,
                        "significant": srm.significant,
                        "status": srm.status,
                        "significance_level": srm.significance_level,
                        "observed_counts": srm.observed_counts,
                        "expected_counts": srm.expected_counts,
                        "warning_is_not_an_automatic_failure": True,
                    },
                    "guardrails": guardrail_diagnostics(checks),
                }
                result_records.append(
                    (
                        result_id,
                        experiment_id,
                        metric["metric_definition_id"],
                        int(metric["version"]),
                        control["variant_id"],
                        treatment["variant_id"],
                        computed_at,
                        analysis_plan_version,
                        window_start_text,
                        window_end_text,
                        estimate.control_n,
                        estimate.treatment_n,
                        estimate.effect_estimate,
                        estimate.standard_error,
                        estimate.confidence_level,
                        estimate.ci_lower,
                        estimate.ci_upper,
                        estimate.p_value,
                        srm.p_value,
                        srm.status,
                        guardrail_status,
                        decision,
                        ANALYSIS_METHOD,
                        json.dumps(analysis_config, sort_keys=True, separators=(",", ":")),
                        snapshot_hash,
                    )
                )
                results.append(
                    {
                        "result_id": result_id,
                        "experiment_id": experiment_id,
                        "metric_definition_id": metric["metric_definition_id"],
                        "metric_definition_version": int(metric["version"]),
                        "control_variant_id": control["variant_id"],
                        "treatment_variant_id": treatment["variant_id"],
                        "effect_estimate": estimate.effect_estimate,
                        "standard_error": estimate.standard_error,
                        "inference_method": estimate.inference_method,
                        "p_value": estimate.p_value,
                        "ci_lower": estimate.ci_lower,
                        "ci_upper": estimate.ci_upper,
                        "confidence_level": estimate.confidence_level,
                        "control_n": estimate.control_n,
                        "treatment_n": estimate.treatment_n,
                        "srm_p_value": srm.p_value,
                        "srm_status": srm.status,
                        "guardrail_status": guardrail_status,
                        "decision": decision,
                        "analysis_plan_version": analysis_plan_version,
                        "input_snapshot_hash": snapshot_hash,
                    }
                )

            with connection:
                connection.executemany(
                    """
                    INSERT INTO experiment_results (
                        result_id, experiment_id, metric_definition_id,
                        metric_definition_version, control_variant_id,
                        treatment_variant_id, computed_at, analysis_plan_version,
                        outcome_window_start, outcome_window_end, control_n,
                        treatment_n, effect_estimate, standard_error,
                        confidence_level, ci_lower, ci_upper, p_value,
                        srm_p_value, srm_status, guardrail_status, decision,
                        analysis_method, analysis_config_json, input_snapshot_hash
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?
                    )
                    """,
                    result_records,
                )
            return results

    def _load_inputs(
        self,
        connection: sqlite3.Connection,
        experiment_id: str,
    ) -> dict[str, pd.DataFrame]:
        experiment = pd.read_sql_query(
            "SELECT * FROM experiments WHERE experiment_id = ?",
            connection,
            params=(experiment_id,),
        )
        if experiment.empty:
            raise ValueError(f"experiment not found: {experiment_id}")

        variants = pd.read_sql_query(
            """
            SELECT variant_id, experiment_id, variant_key, display_name, is_control,
                   allocation_probability
            FROM variants
            WHERE experiment_id = ?
            ORDER BY variant_key
            """,
            connection,
            params=(experiment_id,),
        )
        assignments = pd.read_sql_query(
            """
            SELECT assignment_id, experiment_id, variant_id, audience_member_id,
                   assigned_at, assignment_probability, randomization_bucket
            FROM assignments
            WHERE experiment_id = ?
            ORDER BY assignment_id
            """,
            connection,
            params=(experiment_id,),
        )
        if assignments.empty:
            raise ValueError(f"experiment has no assignments: {experiment_id}")

        metric_id = experiment.loc[0, "primary_metric_definition_id"]
        if not metric_id:
            raise ValueError(f"experiment has no primary metric: {experiment_id}")
        primary_metric = pd.read_sql_query(
            """
            SELECT * FROM metric_definitions
            WHERE metric_definition_id = ? AND experiment_id = ?
            """,
            connection,
            params=(metric_id, experiment_id),
        )
        if primary_metric.empty:
            raise ValueError(f"primary metric definition not found: {metric_id}")

        guardrails = pd.read_sql_query(
            """
            SELECT g.guardrail_id, g.experiment_id, g.metric_definition_id,
                   g.comparison_direction, g.max_regression, g.severity,
                   m.version, m.metric_key, m.metric_type, m.unit,
                   m.aggregation, m.denominator, m.attribution_window_days,
                   m.definition_json, m.content_hash
            FROM guardrail_metrics AS g
            JOIN metric_definitions AS m
              ON m.metric_definition_id = g.metric_definition_id
             AND m.experiment_id = g.experiment_id
            WHERE g.experiment_id = ? AND g.enabled = 1
            ORDER BY g.guardrail_id
            """,
            connection,
            params=(experiment_id,),
        )
        metric_ids = [metric_id, *guardrails["metric_definition_id"].tolist()]
        placeholders = ",".join("?" for _ in metric_ids)
        conversions = pd.read_sql_query(
            f"""
            SELECT conversion_event_id, assignment_id, experiment_id,
                   metric_definition_id, occurred_at, value
            FROM conversion_events
            WHERE experiment_id = ? AND metric_definition_id IN ({placeholders})
            ORDER BY conversion_event_id
            """,
            connection,
            params=(experiment_id, *metric_ids),
        )
        return {
            "experiment": experiment,
            "variants": variants,
            "assignments": assignments,
            "primary_metric": primary_metric,
            "guardrails": guardrails,
            "conversions": conversions,
        }

    @staticmethod
    def _snapshot_hash(inputs: dict[str, pd.DataFrame]) -> str:
        digest = hashlib.sha256()
        for name in (
            "experiment",
            "variants",
            "assignments",
            "primary_metric",
            "guardrails",
            "conversions",
        ):
            digest.update(name.encode("utf-8"))
            digest.update(
                inputs[name]
                .to_json(orient="split", date_format="iso", double_precision=15)
                .encode("utf-8")
            )
        return digest.hexdigest()

    @staticmethod
    def _outcomes_for_metric(
        assignments: pd.DataFrame,
        conversions: pd.DataFrame,
        metric: pd.Series,
    ) -> pd.DataFrame:
        selected = conversions.loc[
            conversions["metric_definition_id"] == metric["metric_definition_id"]
        ].copy()
        cohort = assignments[["assignment_id", "variant_id", "assigned_at"]].copy()
        cohort["assigned_at"] = pd.to_datetime(cohort["assigned_at"], utc=True)
        days = int(metric["attribution_window_days"])
        cohort["window_end"] = cohort["assigned_at"] + pd.Timedelta(days=days)
        if selected.empty:
            cohort["outcome"] = 0.0
            return cohort[["assignment_id", "variant_id", "outcome"]]

        selected["occurred_at"] = pd.to_datetime(selected["occurred_at"], utc=True)
        merged = selected.merge(
            cohort[["assignment_id", "assigned_at", "window_end"]],
            on="assignment_id",
            how="inner",
            validate="many_to_one",
        )
        eligible = merged.loc[
            (merged["occurred_at"] >= merged["assigned_at"])
            & (merged["occurred_at"] <= merged["window_end"])
        ].copy()
        if metric["metric_type"] == "binary":
            grouped = eligible.groupby("assignment_id")["value"].sum().clip(upper=1)
        elif metric["aggregation"] == "mean":
            grouped = eligible.groupby("assignment_id")["value"].mean()
        elif metric["aggregation"] in {"count", "unique_count"}:
            grouped = eligible.groupby("assignment_id")["conversion_event_id"].count()
        else:
            grouped = eligible.groupby("assignment_id")["value"].sum()
        cohort["outcome"] = cohort["assignment_id"].map(grouped).fillna(0.0)
        return cohort[["assignment_id", "variant_id", "outcome"]]

    @staticmethod
    def _estimate(
        metric_type: str,
        control: np.ndarray,
        treatment: np.ndarray,
        confidence_level: float,
    ) -> EffectEstimate:
        if metric_type == "binary":
            return estimate_binary_effect(
                control,
                treatment,
                confidence_level=confidence_level,
            )
        if metric_type in {"continuous", "count", "currency"}:
            return estimate_continuous_effect(
                control,
                treatment,
                confidence_level=confidence_level,
            )
        raise ValueError(f"unsupported metric type: {metric_type}")

    def _evaluate_guardrails(
        self,
        assignments: pd.DataFrame,
        conversions: pd.DataFrame,
        guardrails: pd.DataFrame,
        control_variant_id: str,
        treatment_variant_id: str,
    ) -> list[GuardrailCheck]:
        checks = []
        for guardrail in guardrails.to_dict(orient="records"):
            metric = pd.Series(guardrail)
            outcomes = self._outcomes_for_metric(assignments, conversions, metric)
            control_values = outcomes.loc[
                outcomes["variant_id"] == control_variant_id, "outcome"
            ].to_numpy(dtype=float)
            treatment_values = outcomes.loc[
                outcomes["variant_id"] == treatment_variant_id, "outcome"
            ].to_numpy(dtype=float)
            if control_values.size < 2 or treatment_values.size < 2:
                raise ValueError(
                    f"guardrail {guardrail['guardrail_id']} requires at least two "
                    "observations in both control and treatment"
                )
            checks.append(
                check_guardrail(
                    guardrail_id=guardrail["guardrail_id"],
                    metric_definition_id=guardrail["metric_definition_id"],
                    control_value=float(np.mean(control_values)),
                    treatment_value=float(np.mean(treatment_values)),
                    comparison_direction=guardrail["comparison_direction"],
                    max_regression=float(guardrail["max_regression"]),
                    severity=guardrail["severity"],
                )
            )
        return checks

    @staticmethod
    def _decision(estimate: EffectEstimate, guardrail_status: str) -> str:
        if guardrail_status == "fail":
            return "do_not_ship"
        if guardrail_status == "warning":
            return "iterate"
        if estimate.effect_estimate > 0 and estimate.p_value < 0.05:
            return "ship"
        if estimate.p_value < 0.05 and estimate.effect_estimate < 0:
            return "do_not_ship"
        return "inconclusive"

    @staticmethod
    def _next_result_number(connection: sqlite3.Connection) -> int:
        row = connection.execute(
            """
            SELECT COALESCE(MAX(CAST(substr(result_id, 5) AS INTEGER)), 0) + 1
            FROM experiment_results
            """
        ).fetchone()
        return int(row[0])
