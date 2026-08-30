from decimal import Decimal

import pytest
from pydantic import ValidationError

from ehrfs.catalog.coverage import CoverageInputs, calculate_coverage


def test_coverage_formulas_are_distinct() -> None:
    metric = calculate_coverage(
        CoverageInputs(
            eligible_opportunities=100,
            recorded_responses=87,
            usable_responses=84,
            positive_events=21,
        )
    )
    assert metric.completion == Decimal("0.8700")
    assert metric.usable_coverage == Decimal("0.8400")
    assert metric.prevalence == Decimal("0.2500")


def test_unknown_denominator_reports_observed_count() -> None:
    metric = calculate_coverage(
        CoverageInputs(recorded_responses=10, usable_responses=8, positive_events=2)
    )
    assert metric.completion is None
    assert metric.usable_coverage is None
    assert metric.observed_count == 10
    assert not metric.denominator_known


def test_invalid_coverage_counts_are_rejected() -> None:
    with pytest.raises(ValidationError, match="cannot exceed"):
        CoverageInputs(recorded_responses=3, usable_responses=4, positive_events=0)
