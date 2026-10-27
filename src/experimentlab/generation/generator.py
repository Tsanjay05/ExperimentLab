"""Reproducibly generate ExperimentLab's baseline synthetic dataset."""

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

import numpy as np
import pandas as pd

from experimentlab.config import (
    DEFAULT_DATABASE_PATH,
    DEFAULT_SEED,
    PROJECT_ROOT,
)
from experimentlab.generation.scenarios import validate_scenario_fixtures
from experimentlab.storage.database import connect, initialize_database

EXPERIMENT_COUNT = 10
USERS_PER_EXPERIMENT = 5_000
USER_COUNT = EXPERIMENT_COUNT * USERS_PER_EXPERIMENT
EXPOSURE_RATE = 0.93
EXPOSURE_TELEMETRY_RATE = 0.95
LATE_CONVERSION_RATE = 0.20
OUTCOME_WINDOW_DAYS = 7
MAX_CONVERSION_DELAY_DAYS = 14
TABLES_AND_KEYS = (
    ("experiments", "experiment_id"),
    ("variants", "variant_id"),
    ("audience_members", "audience_member_id"),
    ("metric_definitions", "metric_definition_id"),
    ("guardrail_metrics", "guardrail_id"),
    ("assignments", "assignment_id"),
    ("exposure_events", "exposure_event_id"),
    ("conversion_events", "conversion_event_id"),
)

EXPERIMENT_TREATMENT_EFFECTS = (0.020, 0.000, 0.015, -0.010, 0.025, 0.000, 0.018, -0.015, 0.010, 0.000)
GUARDRAIL_REGRESSIONS = (0.000, 0.000, 0.012, 0.000, 0.018, 0.000, 0.000, 0.015, 0.000, 0.000)


@dataclass(frozen=True)
class GenerationResult:
    """Paths, counts, and deterministic fingerprint for a generated dataset."""

    database_path: str
    ground_truth_path: str
    scenarios_path: str
    seed: int
    entity_counts: dict[str, int]
    database_fingerprint: str


def _timestamp_series(base: pd.Series, offsets_seconds: np.ndarray) -> pd.Series:
    return (
        pd.to_datetime(base, utc=True)
        + pd.to_timedelta(offsets_seconds, unit="s")
    ).dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _json_text(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _definition_hash(definition: dict[str, Any]) -> str:
    return hashlib.sha256(_json_text(definition).encode("utf-8")).hexdigest()


def _generate_entities(
    seed: int,
    experiment_count: int,
    users_per_experiment: int,
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    rng = np.random.default_rng(seed)
    experiment_ids = [
        f"EXP-2026-{number:06d}"
        for number in range(1, experiment_count + 1)
    ]
    user_count = experiment_count * users_per_experiment
    user_ids = [f"USR-{number:06d}" for number in range(1, user_count + 1)]
    experiment_indexes = np.repeat(
        np.arange(experiment_count), users_per_experiment
    )
    count = len(user_ids)
    now = "2026-10-22T00:00:00Z"

    starts = pd.Series(
        [
            (datetime(2026, 10, 22, tzinfo=timezone.utc) + timedelta(days=index))
            .strftime("%Y-%m-%dT%H:%M:%SZ")
            for index in range(experiment_count)
        ]
    )
    experiment_frame = pd.DataFrame(
        {
            "experiment_id": experiment_ids,
            "name": [
                f"Synthetic checkout experiment {index + 1:02d}"
                for index in range(experiment_count)
            ],
            "hypothesis": [
                "The treatment variant changes the seven-day conversion rate."
                for _ in experiment_ids
            ],
            "status": ["completed"] * experiment_count,
            "randomization_unit": ["audience_member"] * experiment_count,
            "start_at": starts,
            "end_at": (pd.to_datetime(starts, utc=True) + pd.Timedelta(days=21)).dt.strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "primary_metric_definition_id": [None] * experiment_count,
            "created_at": [now] * experiment_count,
            "updated_at": [now] * experiment_count,
        }
    )

    variant_rows = []
    for experiment_id in experiment_ids:
        for key, label, is_control in (
            ("A", "Control", 1),
            ("B", "Treatment", 0),
        ):
            variant_rows.append(
                {
                    "variant_id": f"VAR-{experiment_id}-{key}",
                    "experiment_id": experiment_id,
                    "variant_key": key,
                    "display_name": label,
                    "is_control": is_control,
                    "allocation_probability": 0.5,
                    "config_json": _json_text({"experience": label.lower()}),
                    "status": "active",
                }
            )
    variant_frame = pd.DataFrame(variant_rows)

    audience_frame = pd.DataFrame(
        {
            "audience_member_id": user_ids,
            "created_at": ["2026-10-01T00:00:00Z"] * count,
            "country": rng.choice(["US", "CA", "GB", "AU", "DE"], size=count),
            "platform": rng.choice(["web", "ios", "android"], size=count),
            "segment": rng.choice(["new", "returning", "loyal"], size=count),
            "pre_experiment_attributes_json": [
                _json_text({"tenure_days": int(value)})
                for value in rng.integers(1, 1500, size=count)
            ],
        }
    )

    metric_rows = []
    primary_metric_ids = []
    for index, experiment_id in enumerate(experiment_ids):
        primary_id = f"MET-{index * 2 + 1:06d}"
        guardrail_id = f"MET-{index * 2 + 2:06d}"
        primary_metric_ids.append(primary_id)
        for metric_id, key, name, metric_type, unit, aggregation, window in (
            (
                primary_id,
                "conversion_rate",
                "Seven-day conversion rate",
                "binary",
                "proportion",
                "proportion",
                OUTCOME_WINDOW_DAYS,
            ),
            (
                guardrail_id,
                "checkout_error_rate",
                "Checkout error rate",
                "binary",
                "proportion",
                "proportion",
                OUTCOME_WINDOW_DAYS,
            ),
        ):
            definition = {
                "metric_key": key,
                "metric_type": metric_type,
                "unit": unit,
                "aggregation": aggregation,
                "attribution_window_days": window,
            }
            metric_rows.append(
                {
                    "metric_definition_id": metric_id,
                    "experiment_id": experiment_id,
                    "metric_key": key,
                    "version": 1,
                    "name": name,
                    "metric_type": metric_type,
                    "unit": unit,
                    "aggregation": aggregation,
                    "denominator": "assigned audience members",
                    "attribution_window_days": window,
                    "definition_json": _json_text(definition),
                    "content_hash": _definition_hash(definition),
                    "created_at": now,
                    "effective_at": now,
                }
            )
    metric_frame = pd.DataFrame(metric_rows)
    experiment_frame["primary_metric_definition_id"] = primary_metric_ids

    user_experiment_ids = np.asarray(experiment_ids, dtype=object)[experiment_indexes]
    randomization_buckets = rng.integers(0, 1_000_000, size=count)
    treatment_assigned = randomization_buckets >= 500_000
    variant_keys = np.where(treatment_assigned, "B", "A")
    variant_ids = np.array(
        [f"VAR-{experiment_id}-{key}" for experiment_id, key in zip(user_experiment_ids, variant_keys)],
        dtype=object,
    )
    assignment_times = _timestamp_series(
        pd.Series(
            [
                starts.iloc[index]
                for index in experiment_indexes
            ]
        ),
        rng.integers(0, 3 * 24 * 60 * 60, size=count),
    )
    assignment_frame = pd.DataFrame(
        {
            "assignment_id": [
                f"ASG-{experiment_id}-{user_id}"
                for experiment_id, user_id in zip(user_experiment_ids, user_ids)
            ],
            "experiment_id": user_experiment_ids,
            "variant_id": variant_ids,
            "audience_member_id": user_ids,
            "assigned_at": assignment_times,
            "assignment_probability": np.full(count, 0.5),
            "randomization_bucket": randomization_buckets,
        }
    )

    reached = rng.random(count) < EXPOSURE_RATE
    telemetry_logged = rng.random(count) < EXPOSURE_TELEMETRY_RATE
    exposure_mask = reached & telemetry_logged
    exposure_positions = np.flatnonzero(exposure_mask)
    exposure_frame = pd.DataFrame(
        {
            "exposure_event_id": [
                f"EXPOS-2026-{number:06d}"
                for number in range(1, len(exposure_positions) + 1)
            ],
            "assignment_id": assignment_frame.loc[
                exposure_positions, "assignment_id"
            ].to_numpy(),
            "experiment_id": user_experiment_ids[exposure_positions],
            "occurred_at": _timestamp_series(
                assignment_times.iloc[exposure_positions].reset_index(drop=True),
                rng.integers(0, 24 * 60 * 60, size=len(exposure_positions)),
            ),
            "event_type": rng.choice(
                ["client_render", "server_render"], size=len(exposure_positions)
            ),
            "source": ["synthetic_simulation"] * len(exposure_positions),
            "payload_json": [_json_text({})] * len(exposure_positions),
        }
    )

    experiment_baselines = rng.uniform(0.08, 0.16, size=experiment_count)
    treatment_effects = np.resize(
        np.asarray(EXPERIMENT_TREATMENT_EFFECTS), experiment_count
    )
    guardrail_baselines = rng.uniform(0.015, 0.035, size=experiment_count)
    guardrail_regressions = np.resize(
        np.asarray(GUARDRAIL_REGRESSIONS), experiment_count
    )
    conversion_probabilities = experiment_baselines[experiment_indexes] + (
        treatment_assigned
        & reached
    ) * treatment_effects[experiment_indexes]
    conversion_success = rng.random(count) < conversion_probabilities
    guardrail_probabilities = guardrail_baselines[experiment_indexes] + (
        treatment_assigned
        & reached
    ) * guardrail_regressions[experiment_indexes]
    guardrail_success = rng.random(count) < guardrail_probabilities

    conversion_positions = np.flatnonzero(conversion_success)
    guardrail_positions = np.flatnonzero(guardrail_success)
    event_rows: list[dict[str, Any]] = []
    event_number = 1
    for metric_ids, positions, event_kind in (
        (
            np.asarray([f"MET-{2 * index + 1:06d}" for index in range(experiment_count)], dtype=object)[
                experiment_indexes
            ],
            conversion_positions,
            "conversion",
        ),
        (
            np.asarray([f"MET-{2 * index + 2:06d}" for index in range(experiment_count)], dtype=object)[
                experiment_indexes
            ],
            guardrail_positions,
            "guardrail",
        ),
    ):
        late = rng.random(len(positions)) < LATE_CONVERSION_RATE
        delays = np.where(
            late,
            rng.integers(OUTCOME_WINDOW_DAYS + 1, MAX_CONVERSION_DELAY_DAYS + 1, size=len(positions)),
            rng.integers(0, OUTCOME_WINDOW_DAYS + 1, size=len(positions)),
        )
        occurred_at = _timestamp_series(
            assignment_times.iloc[positions].reset_index(drop=True),
            delays * 24 * 60 * 60,
        )
        for position, event_time, metric_id in zip(positions, occurred_at, metric_ids[positions]):
            event_rows.append(
                {
                    "conversion_event_id": f"CONV-2026-{event_number:06d}",
                    "assignment_id": assignment_frame.at[position, "assignment_id"],
                    "experiment_id": user_experiment_ids[position],
                    "metric_definition_id": metric_id,
                    "occurred_at": event_time,
                    "value": 1.0,
                    "currency": None,
                    "source": "synthetic_simulation",
                    "payload_json": _json_text({"event_kind": event_kind}),
                }
            )
            event_number += 1
    conversion_frame = pd.DataFrame(
        event_rows,
        columns=[
            "conversion_event_id",
            "assignment_id",
            "experiment_id",
            "metric_definition_id",
            "occurred_at",
            "value",
            "currency",
            "source",
            "payload_json",
        ],
    )

    guardrail_rows = []
    for index, experiment_id in enumerate(experiment_ids):
        guardrail_rows.append(
            {
                "guardrail_id": f"GRD-{index + 1:06d}",
                "experiment_id": experiment_id,
                "metric_definition_id": f"MET-{index * 2 + 2:06d}",
                "comparison_direction": "lower_is_better",
                "threshold": float(guardrail_baselines[index]),
                "max_regression": 0.01,
                "severity": "warning",
                "enabled": 1,
                "created_at": now,
            }
        )
    guardrail_frame = pd.DataFrame(guardrail_rows)

    frames = {
        "experiments": experiment_frame,
        "variants": variant_frame,
        "audience_members": audience_frame,
        "metric_definitions": metric_frame,
        "guardrail_metrics": guardrail_frame,
        "assignments": assignment_frame,
        "exposure_events": exposure_frame,
        "conversion_events": conversion_frame,
    }

    ground_truth = {
        "description": (
            "Validation-only simulation truth. Never use these labels or values "
            "as analytical input features."
        ),
        "seed": seed,
        "experiment_count": experiment_count,
        "users_per_experiment": users_per_experiment,
        "exposure_reach_probability": EXPOSURE_RATE,
        "exposure_telemetry_probability_given_reach": EXPOSURE_TELEMETRY_RATE,
        "late_conversion_probability": LATE_CONVERSION_RATE,
        "outcome_window_days": OUTCOME_WINDOW_DAYS,
        "experiments": [
            {
                "experiment_id": experiment_ids[index],
                "metric_definition_id": primary_metric_ids[index],
                "control_conversion_probability_before_window_censoring": float(
                    experiment_baselines[index]
                ),
                "treatment_on_treated_effect": float(treatment_effects[index]),
                "true_intention_to_treat_effect_in_window": float(
                    treatment_effects[index]
                    * EXPOSURE_RATE
                    * (1 - LATE_CONVERSION_RATE)
                ),
                "control_guardrail_event_probability": float(guardrail_baselines[index]),
                "treatment_guardrail_regression_on_exposed": float(
                    guardrail_regressions[index]
                ),
                "ground_truth_labels": {
                    "has_positive_treatment_effect": bool(treatment_effects[index] > 0),
                    "has_negative_treatment_effect": bool(treatment_effects[index] < 0),
                    "has_guardrail_regression": bool(guardrail_regressions[index] > 0),
                },
                "assigned_members": users_per_experiment,
                "members_reached": int(reached[experiment_indexes == index].sum()),
                "exposure_events_logged": int(exposure_mask[experiment_indexes == index].sum()),
                "members_not_reached": int((~reached[experiment_indexes == index]).sum()),
                "reached_members_missing_exposure_telemetry": int(
                    (reached & ~telemetry_logged)[experiment_indexes == index].sum()
                ),
            }
            for index in range(experiment_count)
        ],
    }

    return frames, ground_truth


def _scenario_fixtures(
    frames: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    assignments = frames["assignments"]
    variants = frames["variants"]
    metrics = frames["metric_definitions"]
    first_assignment = assignments.iloc[0]
    second_assignment = assignments.iloc[1]
    first_experiment = first_assignment["experiment_id"]
    first_variant_id = first_assignment["variant_id"]
    alternate_variant = variants.loc[
        (variants["experiment_id"] == first_experiment)
        & (variants["variant_id"] != first_variant_id)
    ].iloc[0]
    first_metric = metrics.loc[
        (metrics["experiment_id"] == first_experiment)
        & (metrics["metric_key"] == "conversion_rate")
    ].iloc[0]
    assigned_at = datetime.strptime(
        second_assignment["assigned_at"], "%Y-%m-%dT%H:%M:%SZ"
    ).replace(tzinfo=timezone.utc)

    return {
        "description": (
            "Fixture-only negative scenarios. These intentionally invalid records "
            "are not inserted into the baseline SQLite database and must not be "
            "treated as analytical data."
        ),
        "fixtures": [
            {
                "scenario_id": "multiple_variant_assignments",
                "label": "user assigned to multiple variants",
                "anomaly": {
                    "experiment_id": first_experiment,
                    "audience_member_id": first_assignment["audience_member_id"],
                    "existing_assignment_id": first_assignment["assignment_id"],
                    "existing_variant_id": first_variant_id,
                    "attempted_assignment_id": (
                        f"SCN-ASG-{first_experiment}-"
                        f"{first_assignment['audience_member_id']}-2"
                    ),
                    "attempted_variant_id": alternate_variant["variant_id"],
                    "violated_invariant": (
                        "one assignment per audience member per experiment"
                    ),
                },
                "issue_type": "multiple_variant_assignments",
                "expected_finding": (
                    "reject a second assignment for the same user and experiment"
                ),
            },
            {
                "scenario_id": "exposure_before_assignment",
                "label": "exposure timestamp precedes assignment",
                "anomaly": {
                    "scenario_event_id": "SCN-EXPOSURE-BEFORE-ASSIGNMENT-000001",
                    "assignment_id": second_assignment["assignment_id"],
                    "experiment_id": second_assignment["experiment_id"],
                    "assignment_at": second_assignment["assigned_at"],
                    "exposure_at": (assigned_at - timedelta(minutes=1)).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                    "violated_invariant": "exposure event must not precede assignment",
                },
                "issue_type": "exposure_before_assignment",
                "expected_finding": (
                    "the SQLite event-timing trigger rejects the exposure"
                ),
            },
            {
                "scenario_id": "inconsistent_outcome_window",
                "label": "analysis window conflicts with metric definition",
                "anomaly": {
                    "metric_definition_id": first_metric["metric_definition_id"],
                    "metric_definition_version": int(first_metric["version"]),
                    "metric_attribution_window_days": int(
                        first_metric["attribution_window_days"]
                    ),
                    "fixture_analysis_window_days": 14,
                    "violated_invariant": (
                        "result outcome window must agree with the metric definition"
                    ),
                },
                "issue_type": "inconsistent_outcome_window",
                "expected_finding": (
                    "the analysis window conflicts with the metric definition"
                ),
            },
            {
                "scenario_id": "ignored_sample_ratio_mismatch",
                "label": "sample-ratio mismatch diagnostic ignored",
                "anomaly": {
                    "experiment_id": first_experiment,
                    "planned_allocation": {"A": 0.5, "B": 0.5},
                    "fixture_observed_counts": {"A": 3500, "B": 1500},
                    "srm_diagnostic": "warning",
                    "diagnostic_ignored": True,
                    "violated_invariant": (
                        "a detected SRM warning must not be marked as passed or ignored"
                    ),
                },
                "issue_type": "ignored_sample_ratio_mismatch",
                "expected_finding": (
                    "detect significant SRM and report ignoring its warning as a failure"
                ),
            },
            {
                "scenario_id": "metric_definition_changed_after_results",
                "label": "metric definition changed after result snapshot",
                "fixture_only": True,
                "anomaly": {
                    "result_snapshot": {
                        "fixture_result_id": "FIXTURE-RESULT-000001",
                        "computed_at": "2026-11-15T00:00:00Z",
                        "metric_definition_id": first_metric["metric_definition_id"],
                        "metric_definition_version": 1,
                    },
                    "later_definition": {
                        "metric_definition_id": "MET-000002",
                        "metric_key": first_metric["metric_key"],
                        "version": 2,
                        "effective_at": "2026-11-16T00:00:00Z",
                        "definition_change": (
                            "attribution window changed from 7 to 14 days"
                        ),
                    },
                    "expected_validation": (
                        "the prior result remains bound to metric version 1; "
                        "the changed definition must be a new version"
                    ),
                    "note": (
                        "The result snapshot and later version are scenario metadata, "
                        "not rows inserted into the baseline database."
                    ),
                },
                "issue_type": "metric_definition_changed_after_results",
                "expected_finding": (
                    "a real v1 result remains associated with v1 after v2 is inserted"
                ),
            },
        ],
    }


def _python_value(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if pd.isna(value):
        return None
    return value


def _insert_frame(
    connection: sqlite3.Connection,
    table: str,
    frame: pd.DataFrame,
) -> None:
    columns = list(frame.columns)
    placeholders = ", ".join("?" for _ in columns)
    column_sql = ", ".join(f'"{column}"' for column in columns)
    sql = f'INSERT INTO "{table}" ({column_sql}) VALUES ({placeholders})'
    rows = (
        tuple(_python_value(value) for value in row)
        for row in frame.itertuples(index=False, name=None)
    )
    connection.executemany(sql, rows)


def _database_has_data(database_path: Path) -> bool:
    if not database_path.exists() or database_path.stat().st_size == 0:
        return False
    with connect(database_path) as connection:
        for table, _ in TABLES_AND_KEYS:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            if exists and connection.execute(
                f'SELECT 1 FROM "{table}" LIMIT 1'
            ).fetchone():
                return True
    return False


def _database_fingerprint(connection: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    for table, primary_key in TABLES_AND_KEYS:
        digest.update(table.encode("utf-8"))
        for row in connection.execute(
            f'SELECT * FROM "{table}" ORDER BY "{primary_key}"'
        ):
            digest.update(
                json.dumps(tuple(row), separators=(",", ":"), ensure_ascii=True).encode(
                    "utf-8"
                )
            )
            digest.update(b"\n")
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def generate_dataset(
    database_path: str | Path = DEFAULT_DATABASE_PATH,
    seed: int = DEFAULT_SEED,
    ground_truth_path: str | Path = PROJECT_ROOT / "data" / "ground_truth" / "ground_truth.json",
    scenarios_path: str | Path = PROJECT_ROOT / "data" / "ground_truth" / "anomaly_scenarios.json",
    *,
    replace: bool = False,
    experiment_count: int = EXPERIMENT_COUNT,
    users_per_experiment: int = USERS_PER_EXPERIMENT,
) -> GenerationResult:
    """Generate the clean baseline and separate ground-truth/scenario JSON files.

    Existing populated databases and output artifacts are preserved unless the
    caller explicitly opts in with ``replace=True``.
    """
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise ValueError("seed must be a non-negative integer")
    if (
        not isinstance(experiment_count, int)
        or isinstance(experiment_count, bool)
        or not 1 <= experiment_count <= 499_999
    ):
        raise ValueError("experiment_count must be an integer between 1 and 499999")
    if (
        not isinstance(users_per_experiment, int)
        or isinstance(users_per_experiment, bool)
        or users_per_experiment < 2
    ):
        raise ValueError("users_per_experiment must be an integer of at least 2")
    if experiment_count * users_per_experiment > 999_999:
        raise ValueError("the total user count must fit the six-digit user ID format")

    database_file = Path(database_path)
    truth_file = Path(ground_truth_path)
    scenarios_file = Path(scenarios_path)
    output_files = (truth_file, scenarios_file)

    if not replace:
        if _database_has_data(database_file):
            raise FileExistsError(
                f"Database already contains data: {database_file}; "
                "choose a new path or pass replace=True."
            )
        existing_output = next((path for path in output_files if path.exists()), None)
        if existing_output is not None:
            raise FileExistsError(
                f"Output already exists: {existing_output}; "
                "choose new output paths or pass replace=True."
            )
    else:
        for path in (database_file, database_file.with_name(database_file.name + "-wal"),
                     database_file.with_name(database_file.name + "-shm")):
            if path.exists():
                path.unlink()

    frames, ground_truth = _generate_entities(
        seed,
        experiment_count,
        users_per_experiment,
    )
    scenarios = _scenario_fixtures(frames)
    database_file.parent.mkdir(parents=True, exist_ok=True)
    initialize_database(database_file)

    with connect(database_file) as connection:
        with connection:
            for table, _ in TABLES_AND_KEYS:
                if table == "experiments":
                    experiments_for_insert = frames[table].copy()
                    experiments_for_insert["primary_metric_definition_id"] = None
                    _insert_frame(connection, table, experiments_for_insert)
                else:
                    _insert_frame(connection, table, frames[table])
                if table == "metric_definitions":
                    connection.executemany(
                        """
                        UPDATE experiments
                        SET primary_metric_definition_id = ?
                        WHERE experiment_id = ?
                        """,
                        (
                            (row.primary_metric_definition_id, row.experiment_id)
                            for row in frames["experiments"].itertuples(index=False)
                        ),
                    )
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"generated database has foreign-key violations: {violations}")
        fingerprint = _database_fingerprint(connection)

    _write_json(truth_file, ground_truth)
    scenarios = validate_scenario_fixtures(database_file, scenarios)
    _write_json(scenarios_file, scenarios)

    entity_counts = {table: len(frames[table]) for table, _ in TABLES_AND_KEYS}
    return GenerationResult(
        database_path=str(database_file),
        ground_truth_path=str(truth_file),
        scenarios_path=str(scenarios_file),
        seed=seed,
        entity_counts=entity_counts,
        database_fingerprint=fingerprint,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate the seeded ExperimentLab synthetic baseline."
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--experiment-count",
        type=int,
        default=EXPERIMENT_COUNT,
        help=f"Number of experiments to generate (default: {EXPERIMENT_COUNT}).",
    )
    parser.add_argument(
        "--users-per-experiment",
        type=int,
        default=USERS_PER_EXPERIMENT,
        help=(
            "Eligible users per experiment "
            f"(default: {USERS_PER_EXPERIMENT})."
        ),
    )
    parser.add_argument(
        "--ground-truth",
        type=Path,
        default=PROJECT_ROOT / "data" / "ground_truth" / "ground_truth.json",
    )
    parser.add_argument(
        "--scenarios",
        type=Path,
        default=PROJECT_ROOT / "data" / "ground_truth" / "anomaly_scenarios.json",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace the selected database and JSON outputs if they exist.",
    )
    args = parser.parse_args()

    result = generate_dataset(
        database_path=args.database,
        seed=args.seed,
        ground_truth_path=args.ground_truth,
        scenarios_path=args.scenarios,
        replace=args.replace,
        experiment_count=args.experiment_count,
        users_per_experiment=args.users_per_experiment,
    )
    print(json.dumps(asdict(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
