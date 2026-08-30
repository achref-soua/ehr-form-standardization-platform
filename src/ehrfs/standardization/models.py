"""Standardization outputs before OMOP publication."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from ehrfs.domain.enums import AnswerState, FailureReason, OmopDomain
from ehrfs.domain.models import DomainModel, EvidenceReference, ScalarValue


class ClinicalEvent(DomainModel):
    clinical_event_id: UUID
    canonical_event_id: UUID
    establishment_id: str
    patient_pseudonym: str
    encounter_pseudonym: str | None = None
    occurred_at: datetime
    state: AnswerState
    value: ScalarValue | None = None
    unit: str | None = None
    target_domain: OmopDomain
    target_concept_id: int
    target_concept_code: str
    target_concept_name: str
    target_vocabulary_id: str
    source_value: str | None = None
    mapping_id: str
    mapping_release_id: str
    vocabulary_release_id: str
    evidence: tuple[EvidenceReference, ...]


class StandardizationResult(DomainModel):
    event: ClinicalEvent | None = None
    failures: tuple[FailureReason, ...] = ()
    details: tuple[str, ...] = ()

    @property
    def succeeded(self) -> bool:
        return self.event is not None and not self.failures
