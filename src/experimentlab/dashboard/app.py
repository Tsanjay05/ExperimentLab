"""Interactive Streamlit dashboard for ExperimentLab."""

from contextlib import closing
from html import escape
import json
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from experimentlab.analysis.analyzer import Analyzer
from experimentlab.config import DEFAULT_DATABASE_PATH, PROJECT_ROOT
from experimentlab.storage.database import connect


DATABASE_PATH = DEFAULT_DATABASE_PATH
SCENARIOS_PATH = PROJECT_ROOT / "data" / "ground_truth" / "anomaly_scenarios.json"

st.set_page_config(layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
        /* Hide the menu and footer while preserving Streamlit's sidebar controls. */
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def load_experiments(database_path: str) -> pd.DataFrame:
    with closing(connect(database_path)) as connection:
        return pd.read_sql_query(
            """
            SELECT e.experiment_id, e.name, e.hypothesis, e.status, e.start_at,
                   e.end_at, e.primary_metric_definition_id,
                   m.name AS primary_metric_name, m.metric_key,
                   m.metric_type, m.unit, m.version AS metric_version
            FROM experiments AS e
            LEFT JOIN metric_definitions AS m
              ON m.metric_definition_id = e.primary_metric_definition_id
             AND m.experiment_id = e.experiment_id
            ORDER BY e.experiment_id
            """,
            connection,
        )


@st.cache_data(show_spinner=False)
def load_variants(database_path: str, experiment_id: str) -> pd.DataFrame:
    with closing(connect(database_path)) as connection:
        return pd.read_sql_query(
            """
            SELECT variant_id, variant_key, display_name, is_control,
                   allocation_probability, status
            FROM variants
            WHERE experiment_id = ?
            ORDER BY variant_key
            """,
            connection,
            params=(experiment_id,),
        )


@st.cache_data(show_spinner=False)
def load_metrics(database_path: str, experiment_id: str) -> pd.DataFrame:
    with closing(connect(database_path)) as connection:
        return pd.read_sql_query(
            """
            SELECT m.metric_definition_id, m.metric_key, m.version, m.name,
                   m.metric_type, m.unit, m.aggregation,
                   m.attribution_window_days, g.guardrail_id,
                   g.comparison_direction, g.max_regression, g.severity,
                   g.enabled
            FROM metric_definitions AS m
            LEFT JOIN guardrail_metrics AS g
              ON g.metric_definition_id = m.metric_definition_id
             AND g.experiment_id = m.experiment_id
            WHERE m.experiment_id = ?
            ORDER BY m.metric_key, m.version
            """,
            connection,
            params=(experiment_id,),
        )


@st.cache_data(show_spinner=False)
def load_results(database_path: str, experiment_id: str) -> pd.DataFrame:
    with closing(connect(database_path)) as connection:
        return pd.read_sql_query(
            """
            SELECT r.result_id, r.experiment_id, r.metric_definition_id,
                   r.metric_definition_version, r.control_variant_id,
                   r.treatment_variant_id, control.display_name AS control_name,
                   treatment.display_name AS treatment_name, metric.name AS metric_name,
                   metric.unit AS metric_unit, r.computed_at,
                   r.analysis_plan_version, r.outcome_window_start,
                   r.outcome_window_end, r.control_n, r.treatment_n,
                   r.effect_estimate, r.standard_error, r.confidence_level,
                   r.ci_lower, r.ci_upper, r.p_value, r.srm_p_value,
                   r.srm_status, r.guardrail_status, r.decision,
                   r.analysis_config_json, r.input_snapshot_hash
            FROM experiment_results AS r
            JOIN variants AS control
              ON control.variant_id = r.control_variant_id
             AND control.experiment_id = r.experiment_id
            JOIN variants AS treatment
              ON treatment.variant_id = r.treatment_variant_id
             AND treatment.experiment_id = r.experiment_id
            JOIN metric_definitions AS metric
              ON metric.metric_definition_id = r.metric_definition_id
             AND metric.experiment_id = r.experiment_id
            WHERE r.experiment_id = ?
            ORDER BY r.computed_at, r.result_id
            """,
            connection,
            params=(experiment_id,),
        )


def load_scenarios(path: Path) -> dict:
    with path.open(encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict) or not isinstance(payload.get("fixtures"), list):
        raise ValueError(f"Scenario file has an invalid structure: {path}")
    return payload


def result_frame(results: pd.DataFrame) -> pd.DataFrame:
    """Build the human-readable statistical summary table."""
    confidence_percent = (results["confidence_level"] * 100).round(0).astype(int)
    summary = pd.DataFrame(
        {
            "Treatment vs control": (
                results["treatment_name"] + " vs " + results["control_name"]
            ),
            "Metric": results["metric_name"],
            "Absolute treatment effect": results["effect_estimate"],
            "Confidence interval": [
                f"[{low:.4f}, {high:.4f}] ({level}%)"
                for low, high, level in zip(
                    results["ci_lower"],
                    results["ci_upper"],
                    confidence_percent,
                )
            ],
            "P-value": results["p_value"],
            "SRM": results["srm_status"],
            "Guardrail": results["guardrail_status"],
            "Decision": results["decision"],
        }
    )
    return summary


def show_result_alerts(results: pd.DataFrame) -> None:
    for _, result in results.iterrows():
        config = json.loads(result["analysis_config_json"])
        srm = config.get("srm", {})
        comparison = f"{result['treatment_name']} vs {result['control_name']}"
        if result["srm_status"] == "warning":
            st.warning(
                f"Sample-ratio mismatch detected for {comparison} "
                f"(p = {float(result['srm_p_value']):.4g}). This is a diagnostic "
                "warning; assigned users remain in the intention-to-treat analysis."
            )
        if result["guardrail_status"] in {"warning", "fail"}:
            exceeded = [
                item
                for item in config.get("guardrails", [])
                if item.get("exceeded")
            ]
            names = ", ".join(item["guardrail_id"] for item in exceeded) or "guardrail"
            message = (
                f"Guardrail regression exceeded its allowed threshold for "
                f"{comparison}: {names}."
            )
            if result["guardrail_status"] == "fail":
                st.error(message)
            else:
                st.warning(message)
        if srm.get("significant") and result["srm_status"] != "warning":
            st.warning(
                f"Stored SRM status for {comparison} does not match the recorded "
                "significance diagnostic."
            )


def render_results(results: pd.DataFrame) -> None:
    if results.empty:
        st.info("No analysis results are available for this experiment.")
        return

    show_result_alerts(results)
    summary = result_frame(results)
    st.subheader("Statistical results")
    st.dataframe(summary, width="stretch", hide_index=True)

    chart_data = results[
        ["treatment_name", "effect_estimate", "ci_lower", "ci_upper"]
    ].copy()
    chart_data = chart_data.rename(
        columns={
            "treatment_name": "Treatment",
            "effect_estimate": "Absolute uplift",
            "ci_lower": "95% CI lower",
            "ci_upper": "95% CI upper",
        }
    ).set_index("Treatment")
    st.subheader("Absolute treatment effect")
    chart = (
        alt.Chart(chart_data.reset_index())
        .mark_bar(color="#167d9a")
        .encode(
            x=alt.X(
                "Treatment:N",
                sort=None,
                axis=alt.Axis(labelAngle=0, title="Treatment variant"),
            ),
            y=alt.Y("Absolute uplift:Q", title="Treatment effect"),
            tooltip=[
                alt.Tooltip("Treatment:N"),
                alt.Tooltip("Absolute uplift:Q", format=".4f"),
                alt.Tooltip("95% CI lower:Q", format=".4f"),
                alt.Tooltip("95% CI upper:Q", format=".4f"),
            ],
        )
        .properties(height=340)
    )
    st.altair_chart(chart, width="stretch")
    st.caption(
        "Bars show the intention-to-treat absolute effect (treatment minus control). "
        "Confidence intervals are shown in the results table."
    )

    csv = summary.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download results as CSV",
        data=csv,
        file_name=f"{results.iloc[0]['experiment_id']}_analysis_results.csv",
        mime="text/csv",
    )


def main() -> None:
    st.title("ExperimentLab")
    st.caption("A/B testing and experiment validation platform")

    if not DATABASE_PATH.exists():
        st.error(f"Experiment database not found: {DATABASE_PATH}")
        st.code(
            '$env:PYTHONPATH = "src"; '
            ".\\.venv\\Scripts\\python.exe -m experimentlab.generation.generator",
            language="powershell",
        )
        st.stop()

    try:
        experiments = load_experiments(str(DATABASE_PATH))
    except Exception as error:
        st.error(f"Unable to read the ExperimentLab database: {error}")
        st.stop()
    if experiments.empty:
        st.warning("No experiments are available. Generate the baseline dataset first.")
        st.stop()

    selected_id = st.sidebar.selectbox(
        "Select experiment",
        options=experiments["experiment_id"].tolist(),
        format_func=lambda experiment_id: (
            f"{experiment_id} — "
            f"{experiments.loc[experiments['experiment_id'] == experiment_id, 'name'].iloc[0]}"
        ),
    )
    experiment = experiments.loc[
        experiments["experiment_id"] == selected_id
    ].iloc[0]

    overview_tab, scenarios_tab = st.tabs(["Experiment analysis", "Negative scenarios"])
    with overview_tab:
        st.header(experiment["name"])
        st.write(experiment["hypothesis"])
        metadata_columns = st.columns(4)
        metadata = (
            ("Status", experiment["status"] or "Not set"),
            ("Start", experiment["start_at"] or "Not set"),
            ("End", experiment["end_at"] or "Not set"),
            (
                "Primary metric",
                experiment["primary_metric_name"] or "Not configured",
            ),
        )
        for column, (label, value) in zip(metadata_columns, metadata):
            column.markdown(
                f"**{label}**<br>{escape(str(value))}",
                unsafe_allow_html=True,
            )

        try:
            variants = load_variants(str(DATABASE_PATH), selected_id)
            metrics = load_metrics(str(DATABASE_PATH), selected_id)
            with st.expander("Variants and metric definitions"):
                st.markdown("**Variants**")
                st.dataframe(variants, width="stretch", hide_index=True)
                st.markdown("**Metric definitions and guardrails**")
                st.dataframe(metrics, width="stretch", hide_index=True)

            results = load_results(str(DATABASE_PATH), selected_id)
            if results.empty:
                with st.spinner("Running intention-to-treat analysis..."):
                    Analyzer(DATABASE_PATH).analyze(selected_id)
                load_results.clear()
                results = load_results(str(DATABASE_PATH), selected_id)
            render_results(results)
        except Exception as error:
            st.error(f"Analysis could not be loaded or completed: {error}")

    with scenarios_tab:
        st.header("Injected negative scenarios")
        st.caption(
            "These fixtures are isolated from the baseline database and must not be "
            "used as analytical input data."
        )
        if not SCENARIOS_PATH.exists():
            st.warning(f"Scenario fixture file not found: {SCENARIOS_PATH}")
        else:
            try:
                scenario_data = load_scenarios(SCENARIOS_PATH)
                st.info(scenario_data.get("description", "Scenario fixtures"))
                for fixture in scenario_data["fixtures"]:
                    with st.expander(
                        f"{fixture.get('scenario_id', 'scenario')}: "
                        f"{fixture.get('label', 'Unlabelled scenario')}"
                    ):
                        st.json(fixture.get("anomaly", {}))
            except (OSError, json.JSONDecodeError, ValueError) as error:
                st.error(f"Unable to load scenario fixtures: {error}")


if __name__ == "__main__":
    main()
