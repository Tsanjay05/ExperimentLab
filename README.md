# ExperimentLab

ExperimentLab is a reproducible synthetic A/B testing and experiment validation
platform. It creates seeded experiment data in SQLite, estimates intention-to-treat
(ITT) effects, checks assignment balance and guardrails, and provides a Streamlit
dashboard and CSV/JSON exports.

## Features

- Ten synthetic experiments with 5,000 eligible users each (50,000 total), using
  the default seed `20261022`.
- Deterministic, schema-validated IDs and SQLite foreign keys.
- Simulated randomized assignments, exposure telemetry, conversions, delayed
  outcomes, noncompliance, and guardrail events.
- Separate ground-truth labels and five labelled negative scenario fixtures.
- ITT estimates, confidence intervals, p-values, chi-square SRM diagnostics, and
  guardrail checks.
- Append-only metric-definition versions, event history, and experiment results.
- Interactive Streamlit dashboard with experiment selection, scenario inspection,
  charts, alerts, and CSV download.
- Clean analytical input and saved-result exports in CSV and JSON.

## Requirements

- Python 3.12
- PowerShell on Windows (commands below use the project virtual environment)

The project dependencies are declared in `pyproject.toml`. No separate database
server is needed; persistence uses Python's standard-library `sqlite3`.

## Setup

From the project root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
$env:PYTHONPATH = "src"
```

The `dev` extra installs pytest alongside the project dependencies.

## Generate the dataset

Run the seeded full-scale generation pipeline (10 experiments × 5,000 users,
50,000 users total):

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m experimentlab.generation.generator --replace
```

The default database is `data/generated/experimentlab.db`. Ground truth and
scenario fixtures are written separately to `data/ground_truth/`. `--replace`
explicitly replaces those generated outputs, so use it only when you intend to
regenerate the selected database and JSON files. To preserve existing outputs,
omit `--replace`; generation will stop rather than overwrite populated files.

For quick development, use the same generator with a smaller scale and separate
output paths:

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m experimentlab.generation.generator `
  --experiment-count 2 `
  --users-per-experiment 100 `
  --database data\generated\starter.db `
  --ground-truth data\ground_truth\starter_ground_truth.json `
  --scenarios data\ground_truth\starter_scenarios.json
```

Both scale options default to the full 10 × 5,000 profile. The selected ID formats
support up to 499,999 experiments and 999,999 total users; invalid sizes are
rejected rather than generating IDs that violate the schema.

## Run the tests

Run the full test suite:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Or run a focused test module:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_database.py
.\.venv\Scripts\python.exe -m pytest tests\test_generation.py
.\.venv\Scripts\python.exe -m pytest tests\test_analysis.py
.\.venv\Scripts\python.exe -m pytest tests\test_exports.py
```

## Launch the dashboard

Generate the database first if it does not exist. Then launch Streamlit:

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m streamlit run src\experimentlab\dashboard\app.py
```

The app reads the default local database at `data/generated/experimentlab.db`.
It runs analysis for a selected experiment if no result exists yet, then displays
saved results and scenario fixtures.

## Export data and results

The export API writes table-specific CSV and JSON files under `data/exports/` by
default. Ground-truth labels and negative scenario fixtures are deliberately
excluded from clean analytical data exports. The clean SQL seed export includes
the schema and clean input-table rows; saved experiment results remain separate
and can be exported through the existing CSV/JSON result export.

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -c "from experimentlab.exports.export import export_clean_dataset, export_clean_dataset_sql, export_experiment_results; print(export_clean_dataset()); print(export_clean_dataset_sql()); print(export_experiment_results())"
```

The clean dataset includes experiments, variants, audience members, assignments,
exposure events, conversion events, metric definitions, and guardrails. Results are
exported separately from `experiment_results`.
To recreate a clean SQLite database, execute `data/exports/clean_dataset.sql`
with SQLite (for example, open a fresh database connection in Python and call
`executescript` with the file contents). The SQL seed creates the
`experiment_results` table but intentionally does not insert result rows.

## Project layout

```text
src/experimentlab/
├── analysis/       # ITT inference, SRM, guardrail checks, analyzer
├── dashboard/      # Streamlit application
├── exports/        # CSV and JSON output
├── generation/     # Seeded synthetic data and scenario fixtures
└── storage/        # SQLite schema and connection helpers
docs/               # Data dictionary and validation summary
tests/              # Database, generation, analysis, and export tests
```

See [docs/data_dictionary.md](docs/data_dictionary.md) for field definitions and
[docs/validation_summary.md](docs/validation_summary.md) for scenario and validation
behavior.

## Repository

The project source code, tests, synthetic ground-truth fixtures, and documentation are available in the public GitHub repository:

**[ExperimentLab — GitHub Repository](https://github.com/Tsanjay05/ExperimentLab)**

To check the local repository status:

```powershell
git status
```

To publish subsequent changes:

```powershell
git add -A
git commit -m "Describe your changes"
git push
```

Do not commit the local virtual environment, generated SQLite database, or other ignored development artifacts.