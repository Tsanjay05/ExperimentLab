# Prompt history

Prompts below are reproduced from the actual user requests in this conversation.

## Design prompt

I'm building a Python project called ExperimentLab for an A/B Testing and Experiment Validation Platform.

This is an individual technical assignment. I want to build a working, tested, reproducible application.

Technology stack:

- Python 3.12
- pandas and NumPy for synthetic data generation
- SciPy for statistical analysis
- SQLite for relational persistence
- Streamlit for the dashboard
- pytest for automated tests

The assignment requires:

1. Nine core entities: Experiment, Variant, AudienceMember, Assignment, ExposureEvent, ConversionEvent, MetricDefinition, GuardrailMetric and ExperimentResult.
2. 50,000 eligible users across 10 experiments, generated using a fixed default seed of 20261022.
3. Deterministic IDs, valid foreign keys, documented relationships and immutable event history.
4. Randomized assignments, exposure and conversion simulation, noncompliance, missing telemetry, delayed conversions and guardrail regressions.
5. Five labelled negative scenarios: a user assigned to multiple variants, exposure before assignment, an inconsistent outcome window, ignored sample-ratio mismatch and metric definition changes after results.
6. Separate ground-truth labels that are never used as analytical input features.
7. Statistical treatment-effect estimates, confidence intervals, p-values, guardrail checks and randomization validation.
8. CSV/JSON exports, SQL seed data, reproducibility checks and a validation summary.
9. A README, data dictionary, automated tests and PROMPT_HISTORY.md for actual AI prompts.
First, inspect the current project folder and propose a clean, modular directory structure and implementation plan.

Define the nine entities, their fields, primary keys, foreign keys, relationships, validation rules and lifecycle states. Explain how metric-definition versions and event history will be preserved.

Do not generate the full application yet. Do not install additional packages without asking. Do not claim that anything has been tested unless it has actually been executed.

Return the proposed architecture and schema so I can review them before implementation.

## Implementation prompt

The proposed ExperimentLab architecture looks good. Before implementation, apply these design decisions:

1. Generate 50,000 eligible audience members total across 10 experiments, with 5,000 per experiment in the baseline dataset.
2. Use the exact required ID formats:

- Experiment: EXP-2026-000001
- Variant: VAR-{experiment_id}-A
- Assignment: ASG-{experiment_id}-{user_id}
- Exposure: EXPOS-2026-000001
- Conversion: CONV-2026-000001
Use stable, zero-padded user IDs. Keep all IDs and foreign-key references consistent.
3. Create the nine core entities and document every field's type, required/optional status, allowed values, units, uniqueness and validation rule.
4. Implement SQLite tables with primary keys, foreign keys, uniqueness constraints, appropriate CHECK constraints and foreign-key enforcement on every connection.
5. Ensure assignments reference a variant belonging to the same experiment. Ensure metric definitions and guardrails reference the correct experiment.
6. Preserve metric-definition versions, event history and experiment results. Do not silently overwrite previous definitions or results.
7. Keep the normal baseline data valid. Store deliberate anomaly scenarios separately and maintain separate ground-truth labels.
8. Use intention-to-treat as the primary analysis approach. Treat SRM as a diagnostic warning based on the planned allocation ratio.
9. Record the analysis-plan version, metric-definition version, outcome window and input snapshot hash with each result.
10. Support the required scenarios: multiple variant assignments, exposure before assignment, inconsistent outcome windows, ignored SRM and metric changes after results.
Now implement only:

- The initial package and directory structure.
- pyproject.toml and .gitignore.
- src/experimentlab/__init__.py.
- src/experimentlab/config.py.
- src/experimentlab/storage/schema.sql.
- src/experimentlab/storage/database.py.
- docs/data_dictionary.md.
- A small schema/database test in tests/test_database.py.
Do not implement the generator, statistics or dashboard yet. Do not add dependencies beyond those already installed unless you ask first.

Use Python 3.12 and the standard-library sqlite3 module for database operations. Enable SQLite foreign keys on every connection. Include a simple initialization function that creates the schema in a local database under data/generated/.

Add tests that verify all nine entities exist, foreign keys are enabled, primary-key and uniqueness constraints work, and invalid references are rejected.

Record this actual prompt and our previous design prompt in PROMPT_HISTORY.md, preserving their real wording. Do not fabricate previous prompts or test results.

After implementation, explain which files you created and give me the exact PowerShell commands to run the tests. Do not claim the tests passed until they have actually run.

## Synthetic data generator prompt

Implement Phase 3: Synthetic Data Generator for ExperimentLab.
Use the existing database schema and the fixed seed `20261022`.

Requirements:

1. Create a generation module in `src/experimentlab/generation/` (e.g., `generator.py`) using `pandas` and `numpy` for efficient data synthesis.
2. Generate exactly 10 experiments and 50,000 audience members (5,000 eligible members per experiment).
3. Generate Variants, MetricDefinitions, and GuardrailMetrics for each experiment. Ensure ID formats exactly match the schema rules.
4. Simulate Assignments, ExposureEvents, and ConversionEvents. Incorporate simulated treatment effects (e.g., positive uplift for certain variants) and delayed conversions.
5. Inject the 5 requested negative scenarios:

- A user assigned to multiple variants.
- Exposure before assignment.
- Inconsistent outcome window.
- Ignored sample-ratio mismatch (SRM).
- Metric definition changes after results.
6. Keep baseline data clean. Store the injected anomalies and their ground-truth labels separately (e.g., in a separate `data/ground_truth/` JSON or CSV, or separate SQLite tables) so they do not pollute the primary analytical inputs.
7. Create `tests/test_generation.py` to assert the fixed seed's reproducibility, verify the 50,000 user count, and ensure no foreign key violations occur during standard data insertion.
8. Provide an entry-point function or script to run the generation pipeline from the command line.
Do not implement the statistical analysis or dashboard yet. Do not add dependencies beyond those already installed unless you ask first. Record this prompt in `PROMPT_HISTORY.md`. Output the exact PowerShell commands to run the generation script and the new tests.

## Statistical analysis prompt

Implement Phase 4: Validation and Statistical Analysis for ExperimentLab.

Requirements:

1. In `src/experimentlab/analysis/`, implement modules for inference, guardrails, and randomization checks. Use `scipy.stats` and `pandas`.
2. Implement a Sample Ratio Mismatch (SRM) check using a Chi-square test. Return the p-value and a flag indicating if the mismatch is statistically significant (e.g., p < 0.001). Treat this as a diagnostic warning, not an automatic failure.
3. Implement intention-to-treat (ITT) analysis. Calculate the Absolute Treatment Effect (uplift), p-values (using a two-sided t-test or proportion Z-test as appropriate for the metric type), and 95% Confidence Intervals comparing each variant against the control.
4. Implement guardrail validation: check if the variant regresses the guardrail metric beyond the allowed `max_regression` threshold.
5. Create an `Analyzer` class or pipeline that takes an `experiment_id`, pulls the clean baseline data from SQLite, performs the SRM check, calculates primary metric uplift, checks guardrails, and writes the final summary to the `ExperimentResult` table (linking the exact `metric_definition_id`).
6. Create `tests/test_analysis.py`. Use a known subset of the generated seed data (or mock data) to assert that the confidence interval and p-value math is correct, and that SRM detects severe imbalances.
7. Record this prompt in `PROMPT_HISTORY.md`.
Do not build the dashboard yet. Output the exact PowerShell commands to run the analysis tests.

## Interactive dashboard prompt

Implement Phase 5: Interactive Dashboard for ExperimentLab.

Requirements:

1. Create a Streamlit application in `src/experimentlab/dashboard/app.py`.
2. The dashboard must connect to the local SQLite database (`data/generated/experimentlab.db`) to read experiments, variants, and metrics.
3. Provide a sidebar to select an experiment.
4. For the selected experiment, display its metadata (hypothesis, dates) and run the `Analyzer` (from Phase 4) to generate and save results if they don't already exist in the `ExperimentResult` table, then query and display those results.
5. Display the statistical analysis in a clear table: Absolute Treatment Effect, 95% Confidence Intervals, and p-values.
6. Visualize the results (e.g., a bar chart showing conversion rates or uplift).
7. Display clear UI alerts (e.g., using `st.warning` or `st.error`) if there is a Sample Ratio Mismatch (SRM) or if a guardrail metric regressed beyond the allowed threshold.
8. Provide a button to download the analysis results as a CSV file.
9. Create a separate tab in the dashboard to load and display the injected negative scenarios from `data/ground_truth/anomaly_scenarios.json` so we can inspect them.
10. Record this prompt in `PROMPT_HISTORY.md`.
Do not implement Phase 6 (Tests and submission) yet. Output the exact PowerShell command to launch the Streamlit app.

## Tests and submission prompt (Phase 6)

Implement Phase 6: Tests and Submission for ExperimentLab.

Requirements:

1. Implement export functionality in `src/experimentlab/exports/export.py` to allow exporting the clean analytical dataset and the generated experiment results to CSV and JSON formats.
2. Create `tests/test_exports.py` to verify that these export functions work correctly.
3. Create `docs/validation_summary.md` explaining how the pipeline handles the 5 labelled negative scenarios, SRM, and guardrail validations.
4. Generate a comprehensive `README.md` at the project root. It should include: a project overview, setup instructions, commands to run the generator, commands to run the tests, and commands to launch the dashboard.
5. Review `PROMPT_HISTORY.md` to ensure all prompts from Phase 1 through Phase 6 are recorded exactly as entered.
6. Provide me with the exact Git and GitHub CLI (or standard Git) commands to initialize the repository, stage all files, create the initial commit, and push this to a new public GitHub repository.
Do not generate any more features. Output the Git commands so I can submit my assignment.
