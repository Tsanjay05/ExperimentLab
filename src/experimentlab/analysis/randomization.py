"""Randomization balance diagnostics."""

from dataclasses import dataclass
from typing import Mapping

from scipy import stats


SRM_SIGNIFICANCE_LEVEL = 0.001


@dataclass(frozen=True)
class SRMResult:
    """Chi-square sample-ratio mismatch diagnostic."""

    statistic: float
    p_value: float
    significant: bool
    status: str
    observed_counts: dict[str, int]
    expected_counts: dict[str, float]
    significance_level: float = SRM_SIGNIFICANCE_LEVEL


def check_sample_ratio_mismatch(
    observed_counts: Mapping[str, int],
    planned_allocation: Mapping[str, float],
    *,
    significance_level: float = SRM_SIGNIFICANCE_LEVEL,
) -> SRMResult:
    """Compare observed assignment counts with planned allocation using chi-square.

    The diagnostic is a warning, not an instruction to exclude observations.
    """
    if not observed_counts:
        raise ValueError("observed_counts must include at least one variant")
    if set(observed_counts) != set(planned_allocation):
        raise ValueError("observed counts and planned allocation must have matching variants")
    if not 0 < significance_level < 1:
        raise ValueError("significance_level must be between zero and one")
    if any(not isinstance(value, int) or value < 0 for value in observed_counts.values()):
        raise ValueError("observed counts must be non-negative integers")
    if any(value <= 0 for value in planned_allocation.values()):
        raise ValueError("planned allocation probabilities must be positive")

    total = sum(observed_counts.values())
    allocation_total = sum(planned_allocation.values())
    if total == 0:
        raise ValueError("cannot evaluate SRM with no assignments")
    if abs(allocation_total - 1.0) > 1e-9:
        raise ValueError("planned allocation probabilities must sum to 1")

    variants = list(planned_allocation)
    observed = [observed_counts[variant] for variant in variants]
    expected = [total * planned_allocation[variant] for variant in variants]
    statistic, p_value = stats.chisquare(f_obs=observed, f_exp=expected)
    significant = bool(p_value < significance_level)
    return SRMResult(
        statistic=float(statistic),
        p_value=float(p_value),
        significant=significant,
        status="warning" if significant else "pass",
        observed_counts=dict(observed_counts),
        expected_counts={
            variant: float(total * planned_allocation[variant])
            for variant in variants
        },
        significance_level=significance_level,
    )
