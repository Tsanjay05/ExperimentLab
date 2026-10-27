"""Guardrail regression checks for treatment variants."""

from dataclasses import dataclass
import math
from typing import Mapping


@dataclass(frozen=True)
class GuardrailCheck:
    """A treatment-versus-control point-estimate guardrail evaluation."""

    guardrail_id: str
    metric_definition_id: str
    control_value: float
    treatment_value: float
    regression: float
    max_regression: float
    exceeded: bool
    severity: str


def check_guardrail(
    *,
    guardrail_id: str,
    metric_definition_id: str,
    control_value: float,
    treatment_value: float,
    comparison_direction: str,
    max_regression: float,
    severity: str,
) -> GuardrailCheck:
    """Flag when treatment regresses beyond the configured allowance."""
    try:
        control_value = float(control_value)
        treatment_value = float(treatment_value)
        max_regression = float(max_regression)
    except (TypeError, ValueError) as error:
        raise ValueError("guardrail values must be numeric") from error
    if not all(
        math.isfinite(value)
        for value in (control_value, treatment_value, max_regression)
    ):
        raise ValueError("guardrail values must be finite")
    if comparison_direction == "lower_is_better":
        regression = treatment_value - control_value
    elif comparison_direction == "higher_is_better":
        regression = control_value - treatment_value
    else:
        raise ValueError(f"unsupported guardrail direction: {comparison_direction}")
    if max_regression < 0:
        raise ValueError("max_regression must be non-negative")
    if severity not in {"info", "warning", "blocker"}:
        raise ValueError(f"unsupported guardrail severity: {severity}")

    return GuardrailCheck(
        guardrail_id=guardrail_id,
        metric_definition_id=metric_definition_id,
        control_value=control_value,
        regression=float(regression),
        treatment_value=treatment_value,
        max_regression=max_regression,
        exceeded=bool(regression > max_regression),
        severity=severity,
    )


def summarize_guardrails(checks: list[GuardrailCheck]) -> str:
    """Return stored status; blocker regressions fail, softer ones warn."""
    if any(check.exceeded and check.severity == "blocker" for check in checks):
        return "fail"
    if any(check.exceeded for check in checks):
        return "warning"
    return "pass"


def guardrail_diagnostics(
    checks: list[GuardrailCheck],
) -> list[Mapping[str, object]]:
    """Convert checks into JSON-serializable detail for result configuration."""
    return [
        {
            "guardrail_id": check.guardrail_id,
            "metric_definition_id": check.metric_definition_id,
            "control_value": check.control_value,
            "treatment_value": check.treatment_value,
            "regression": check.regression,
            "max_regression": check.max_regression,
            "exceeded": check.exceeded,
            "severity": check.severity,
        }
        for check in checks
    ]
