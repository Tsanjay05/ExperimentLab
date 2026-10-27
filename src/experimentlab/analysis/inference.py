"""Intention-to-treat effect estimates and frequentist inference."""

from dataclasses import dataclass

import numpy as np
from scipy import stats


@dataclass(frozen=True)
class EffectEstimate:
    """Treatment-minus-control estimate and its two-sided test/interval."""

    control_mean: float
    treatment_mean: float
    effect_estimate: float
    standard_error: float
    confidence_level: float
    ci_lower: float
    ci_upper: float
    p_value: float
    control_n: int
    treatment_n: int
    inference_method: str = "unspecified"
    control_successes: int | None = None
    treatment_successes: int | None = None


def _validate_samples(control: np.ndarray, treatment: np.ndarray) -> None:
    if control.ndim != 1 or treatment.ndim != 1:
        raise ValueError("control and treatment outcomes must be one-dimensional")
    if len(control) < 2 or len(treatment) < 2:
        raise ValueError("at least two assigned observations are required per arm")
    if not np.isfinite(control).all() or not np.isfinite(treatment).all():
        raise ValueError("outcomes must contain only finite values")


def _validate_confidence_level(confidence_level: float) -> float:
    try:
        confidence_level = float(confidence_level)
    except (TypeError, ValueError) as error:
        raise ValueError("confidence_level must be numeric") from error
    if not np.isfinite(confidence_level) or not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be between zero and one")
    return confidence_level


def _wilson_interval(successes: int, observations: int, critical_value: float) -> tuple[float, float]:
    proportion = successes / observations
    z_squared = critical_value**2
    denominator = 1 + z_squared / observations
    center = (proportion + z_squared / (2 * observations)) / denominator
    margin = (
        critical_value
        * np.sqrt(
            proportion * (1 - proportion) / observations
            + z_squared / (4 * observations**2)
        )
        / denominator
    )
    return float(center - margin), float(center + margin)


def estimate_binary_effect(
    control_outcomes: np.ndarray,
    treatment_outcomes: np.ndarray,
    *,
    confidence_level: float = 0.95,
) -> EffectEstimate:
    """Estimate a binary risk difference, using score/exact inference for sparse data."""
    control = np.asarray(control_outcomes, dtype=float)
    treatment = np.asarray(treatment_outcomes, dtype=float)
    _validate_samples(control, treatment)
    confidence_level = _validate_confidence_level(confidence_level)
    if not np.isin(control, [0.0, 1.0]).all() or not np.isin(
        treatment, [0.0, 1.0]
    ).all():
        raise ValueError("binary outcomes must contain only 0 or 1")

    control_n = len(control)
    treatment_n = len(treatment)
    control_successes = int(control.sum())
    treatment_successes = int(treatment.sum())
    control_mean = control_successes / control_n
    treatment_mean = treatment_successes / treatment_n
    effect = treatment_mean - control_mean
    standard_error = float(
        np.sqrt(
            control_mean * (1 - control_mean) / control_n
            + treatment_mean * (1 - treatment_mean) / treatment_n
        )
    )
    pooled_mean = (control_successes + treatment_successes) / (
        control_n + treatment_n
    )
    expected_cells = (
        control_n * pooled_mean,
        control_n * (1 - pooled_mean),
        treatment_n * pooled_mean,
        treatment_n * (1 - pooled_mean),
    )
    observed_cells = (
        control_successes,
        control_n - control_successes,
        treatment_successes,
        treatment_n - treatment_successes,
    )
    critical_value = float(stats.norm.ppf(1 - (1 - confidence_level) / 2))
    sparse_table = min(expected_cells) < 5 or min(observed_cells) < 5

    if sparse_table:
        control_interval = _wilson_interval(
            control_successes, control_n, critical_value
        )
        treatment_interval = _wilson_interval(
            treatment_successes, treatment_n, critical_value
        )
        ci_lower = effect - np.sqrt(
            (treatment_mean - treatment_interval[0]) ** 2
            + (control_interval[1] - control_mean) ** 2
        )
        ci_upper = effect + np.sqrt(
            (treatment_interval[1] - treatment_mean) ** 2
            + (control_mean - control_interval[0]) ** 2
        )
        ci_lower = max(-1.0, float(ci_lower))
        ci_upper = min(1.0, float(ci_upper))
        p_value = float(
            stats.fisher_exact(
                [
                    [control_successes, control_n - control_successes],
                    [treatment_successes, treatment_n - treatment_successes],
                ],
                alternative="two-sided",
            ).pvalue
        )
    else:
        ci_lower = effect - critical_value * standard_error
        ci_upper = effect + critical_value * standard_error

    null_standard_error = float(
        np.sqrt(
            pooled_mean
            * (1 - pooled_mean)
            * (1 / control_n + 1 / treatment_n)
        )
    )
    if not sparse_table and null_standard_error != 0:
        z_score = effect / null_standard_error
        p_value = float(2 * stats.norm.sf(abs(z_score)))
    elif not sparse_table:
        p_value = 1.0

    return EffectEstimate(
        control_mean=control_mean,
        treatment_mean=treatment_mean,
        effect_estimate=effect,
        standard_error=standard_error,
        confidence_level=confidence_level,
        ci_lower=float(ci_lower),
        ci_upper=float(ci_upper),
        p_value=p_value,
        control_n=control_n,
        treatment_n=treatment_n,
        inference_method=(
            "fisher_exact_newcombe_wilson"
            if sparse_table
            else "pooled_two_proportion_z_wald"
        ),
        control_successes=control_successes,
        treatment_successes=treatment_successes,
    )


def estimate_continuous_effect(
    control_outcomes: np.ndarray,
    treatment_outcomes: np.ndarray,
    *,
    confidence_level: float = 0.95,
) -> EffectEstimate:
    """Estimate a continuous ITT mean difference with Welch's t-test and CI."""
    control = np.asarray(control_outcomes, dtype=float)
    treatment = np.asarray(treatment_outcomes, dtype=float)
    _validate_samples(control, treatment)
    confidence_level = _validate_confidence_level(confidence_level)

    control_mean = float(np.mean(control))
    treatment_mean = float(np.mean(treatment))
    effect = treatment_mean - control_mean
    control_variance = float(np.var(control, ddof=1))
    treatment_variance = float(np.var(treatment, ddof=1))
    control_component = control_variance / len(control)
    treatment_component = treatment_variance / len(treatment)
    standard_error = float(np.sqrt(control_component + treatment_component))

    if standard_error == 0:
        raise ValueError(
            "Welch inference is undefined when both groups have zero variance"
        )
    else:
        denominator = (
            control_component**2 / (len(control) - 1)
            + treatment_component**2 / (len(treatment) - 1)
        )
        if denominator == 0 or not np.isfinite(denominator):
            raise ValueError("Welch inference is undefined for these outcome groups")
        degrees_freedom = (control_component + treatment_component) ** 2 / denominator
        if not np.isfinite(degrees_freedom) or degrees_freedom <= 0:
            raise ValueError("Welch inference produced invalid degrees of freedom")
        critical_value = float(
            stats.t.ppf(1 - (1 - confidence_level) / 2, degrees_freedom)
        )
        ci_lower = effect - critical_value * standard_error
        ci_upper = effect + critical_value * standard_error
        p_value = float(
            stats.ttest_ind(
                treatment,
                control,
                equal_var=False,
                alternative="two-sided",
            ).pvalue
        )

    return EffectEstimate(
        control_mean=control_mean,
        treatment_mean=treatment_mean,
        effect_estimate=effect,
        standard_error=standard_error,
        confidence_level=confidence_level,
        ci_lower=float(ci_lower),
        ci_upper=float(ci_upper),
        p_value=p_value,
        control_n=len(control),
        treatment_n=len(treatment),
        inference_method="welch_t",
    )
