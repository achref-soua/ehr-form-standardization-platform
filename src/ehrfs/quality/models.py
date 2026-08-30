"""Auditable quality results."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from ehrfs.domain.enums import FailureReason, QualitySeverity
from ehrfs.domain.models import DomainModel


class QualityResult(DomainModel):
    result_id: UUID
    clinical_event_id: UUID | None
    canonical_event_id: UUID
    rule_id: str
    rule_version: str
    passed: bool
    severity: QualitySeverity
    reason: FailureReason | None = None
    message: str
    evaluated_at: datetime
