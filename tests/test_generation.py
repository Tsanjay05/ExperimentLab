import json

import pytest

from experimentlab.generation.generator import generate_dataset
from experimentlab.storage.database import connect


def run_generation(tmp_path, name):
    output_dir = tmp_path / name
    return generate_dataset(
        database_path=output_dir / "experimentlab.db",
        ground_truth_path=output_dir / "ground_truth.json",
        scenarios_path=output_dir / "anomaly_scenarios.json",
    )


@pytest.fixture(scope="module")
def generated_pair(tmp_path_factory):
    root = tmp_path_factory.mktemp("generation")
    return run_generation(root, "first"), run_generation(root, "second")


def test_fixed_seed_generation_is_reproducible(generated_pair):
    first, second = generated_pair

    assert first.seed == second.seed == 20261022
    assert first.database_fingerprint == second.database_fingerprint
    assert first.entity_counts == second.entity_counts

    with open(first.ground_truth_path, encoding="utf-8") as file:
        first_truth = json.load(file)
    with open(second.ground_truth_path, encoding="utf-8") as file:
        second_truth = json.load(file)
    with open(first.scenarios_path, encoding="utf-8") as file:
        first_scenarios = json.load(file)
    with open(second.scenarios_path, encoding="utf-8") as file:
        second_scenarios = json.load(file)

    assert first_truth == second_truth
    assert first_scenarios == second_scenarios
    assert {fixture["scenario_id"] for fixture in first_scenarios["fixtures"]} == {
        "multiple_variant_assignments",
        "exposure_before_assignment",
        "inconsistent_outcome_window",
        "ignored_sample_ratio_mismatch",
        "metric_definition_changed_after_results",
    }


def test_baseline_has_50000_users_and_valid_foreign_keys(generated_pair):
    generated, _ = generated_pair
    with connect(generated.database_path) as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM experiments"
        ).fetchone()[0] == 10
        assert connection.execute(
            "SELECT COUNT(*) FROM audience_members"
        ).fetchone()[0] == 50_000
        assert connection.execute(
            """
            SELECT COUNT(*) FROM assignments
            GROUP BY experiment_id
            HAVING COUNT(*) != 5000
            """
        ).fetchall() == []
        assert connection.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT experiment_id, audience_member_id
                FROM assignments
                GROUP BY experiment_id, audience_member_id
                HAVING COUNT(*) > 1
            )
            """
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM variants"
        ).fetchone()[0] == 20
        assert connection.execute(
            "SELECT COUNT(*) FROM metric_definitions"
        ).fetchone()[0] == 20
        assert connection.execute(
            "SELECT COUNT(*) FROM guardrail_metrics"
        ).fetchone()[0] == 10
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_generator_preserves_existing_data_without_replace(generated_pair):
    generated, _ = generated_pair
    with pytest.raises(FileExistsError, match="already contains data"):
        generate_dataset(
            database_path=generated.database_path,
            ground_truth_path=generated.ground_truth_path,
            scenarios_path=generated.scenarios_path,
        )


def test_primary_generated_ids_follow_schema_formats(generated_pair):
    generated, _ = generated_pair
    with connect(generated.database_path) as connection:
        assert connection.execute(
            "SELECT MIN(experiment_id), MAX(experiment_id) FROM experiments"
        ).fetchone()[:] == ("EXP-2026-000001", "EXP-2026-000010")
        assert connection.execute(
            """
            SELECT COUNT(*) FROM variants
            WHERE variant_id NOT GLOB
                  'VAR-EXP-2026-[0-9][0-9][0-9][0-9][0-9][0-9]-[A-Z]'
            """
        ).fetchone()[0] == 0
        assert connection.execute(
            """
            SELECT COUNT(*) FROM assignments
            WHERE assignment_id !=
                  'ASG-' || experiment_id || '-' || audience_member_id
            """
        ).fetchone()[0] == 0
        assert connection.execute(
            """
            SELECT COUNT(*) FROM exposure_events
            WHERE exposure_event_id NOT GLOB
                  'EXPOS-2026-[0-9][0-9][0-9][0-9][0-9][0-9]'
            """
        ).fetchone()[0] == 0
        assert connection.execute(
            """
            SELECT COUNT(*) FROM conversion_events
            WHERE conversion_event_id NOT GLOB
                  'CONV-2026-[0-9][0-9][0-9][0-9][0-9][0-9]'
            """
        ).fetchone()[0] == 0


def test_generator_supports_a_small_dataset_with_the_default_seed(tmp_path):
    database_path = tmp_path / "small" / "experimentlab.db"
    result = generate_dataset(
        database_path=database_path,
        ground_truth_path=tmp_path / "small" / "ground_truth.json",
        scenarios_path=tmp_path / "small" / "anomaly_scenarios.json",
        experiment_count=2,
        users_per_experiment=25,
    )

    assert result.seed == 20261022
    assert result.entity_counts["experiments"] == 2
    assert result.entity_counts["assignments"] == 50
    with connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM audience_members"
        ).fetchone()[0] == 50
        assert connection.execute(
            """
            SELECT COUNT(*) FROM assignments
            GROUP BY experiment_id
            HAVING COUNT(*) != 25
            """
        ).fetchall() == []
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
