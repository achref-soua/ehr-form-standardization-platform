"""Coverage metrics with an explicit unknown denominator."""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field, model_validator

from ehrfs.domain.models import DomainModel


class CoverageInputs(DomainModel):
    eligible_opportunities: int | None = Field(default=None, ge=0)
    recorded_responses: int = Field(ge=0)
    usable_responses: int = Field(ge=0)
    positive_events: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> CoverageInputs:
        if self.usable_responses > self.recorded_responses:
            msg = "Usable responses cannot exceed recorded responses"
            raise ValueError(msg)
        if self.positive_events > self.usable_responses:
            msg = "Positive events cannot exceed usable responses"
            raise ValueError(msg)
        if (
            self.eligible_opportunities is not None
            and self.recorded_responses > self.eligible_opportunities
        ):
            msg = "Recorded responses cannot exceed eligible opportunities"
            raise ValueError(msg)
        return self


class CoverageMetric(DomainModel):
    completion: Decimal | None
    usable_coverage: Decimal | None
    prevalence: Decimal | None
    observed_count: int
    denominator_known: bool


def _ratio(numerator: int, denominator: int) -> Decimal | None:
    if denominator == 0:
        return None
    return (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.0001"))


def calculate_coverage(inputs: CoverageInputs) -> CoverageMetric:
    eligible = inputs.eligible_opportunities
    return CoverageMetric(
        completion=None if eligible is None else _ratio(inputs.recorded_responses, eligible),
        usable_coverage=None if eligible is None else _ratio(inputs.usable_responses, eligible),
        prevalence=_ratio(inputs.positive_events, inputs.usable_responses),
        observed_count=inputs.recorded_responses,
        denominator_known=eligible is not None,
    )
