import json

from experimentlab.generation.generator import generate_dataset
from experimentlab.storage.database import connect


EXPECTED_ISSUE_TYPES = {
    "multiple_variant_assignments",
    "exposure_before_assignment",
    "inconsistent_outcome_window",
    "ignored_sample_ratio_mismatch",
    "metric_definition_changed_after_results",
}


def test_scenario_fixtures_are_executed_without_changing_baseline(tmp_path):
    database_path = tmp_path / "baseline.db"
    scenarios_path = tmp_path / "scenarios.json"
    result = generate_dataset(
        database_path=database_path,
        ground_truth_path=tmp_path / "ground_truth.json",
        scenarios_path=scenarios_path,
    )

    scenarios = json.loads(scenarios_path.read_text(encoding="utf-8"))
    fixtures = {fixture["issue_type"]: fixture for fixture in scenarios["fixtures"]}

    assert set(fixtures) == EXPECTED_ISSUE_TYPES
    for fixture in fixtures.values():
        assert fixture["expected_finding"]
        assert fixture["observed_outcome"]
        assert fixture["validation_passed"] is True

    multiple_assignment = fixtures["multiple_variant_assignments"]["anomaly"]
    assert (
        multiple_assignment["attempted_assignment_id"]
        != multiple_assignment["existing_assignment_id"]
    )
    assert "one-assignment rule" in fixtures[
        "multiple_variant_assignments"
    ]["observed_outcome"]
    assert "SQLite rejected" in fixtures[
        "exposure_before_assignment"
    ]["observed_outcome"]
    assert "conflicts" in fixtures["inconsistent_outcome_window"]["observed_outcome"]
    assert "ignored despite p=" in fixtures[
        "ignored_sample_ratio_mismatch"
    ]["observed_outcome"]
    assert "v1 result remains bound" in fixtures[
        "metric_definition_changed_after_results"
    ]["observed_outcome"]

    with connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM assignments"
        ).fetchone()[0] == 50_000
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute(
            "SELECT COUNT(*) FROM metric_definitions"
        ).fetchone()[0] == 20
        assert connection.execute(
            "SELECT COUNT(*) FROM experiment_results"
        ).fetchone()[0] == 0

    assert result.entity_counts["assignments"] == 50_000
