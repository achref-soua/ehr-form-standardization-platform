from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ehrfs.domain.enums import AnswerState, OmopDomain, PublicationDecision
from ehrfs.domain.identity import deterministic_uuid
from ehrfs.domain.models import CanonicalAnswerEvent, EvidenceReference
from ehrfs.omop.publisher import publish_event
from ehrfs.quality.engine import QualityEngine
from ehrfs.standardization.models import ClinicalEvent, StandardizationResult


def _canonical(
    evidence: tuple[EvidenceReference, ...], *, state: AnswerState
) -> CanonicalAnswerEvent:
    return CanonicalAnswerEvent(
        event_id=deterministic_uuid("test", state),
        establishment_id="site-a",
        patient_pseudonym="p-demo",
        form_id="form",
        form_version="1",
        source_fingerprint="a" * 64,
        compatibility_fingerprint="b" * 64,
        item_path="Q1",
        state=state,
        authored_at=datetime(2026, 8, 12, tzinfo=UTC),
        evidence=evidence,
    )


@pytest.mark.parametrize(
    "state",
    [
        AnswerState.NOT_RECORDED,
        AnswerState.NOT_APPLICABLE,
        AnswerState.NOT_DISPLAYED_BY_FORM_LOGIC,
        AnswerState.VOIDED,
        AnswerState.SUPERSEDED,
        AnswerState.DELETED,
    ],
)
def test_non_current_lifecycle_events_are_omitted_not_quarantined(
    state: AnswerState,
    evidence: EvidenceReference,
) -> None:
    canonical = _canonical((evidence,), state=state)
    result = QualityEngine().evaluate(
        canonical,
        StandardizationResult(event=None, failures=(), details=()),
        evaluated_at=datetime(2026, 8, 13, tzinfo=UTC),
    )

    assert result.decision == PublicationDecision.OMIT


@pytest.mark.parametrize(
    ("domain", "table"),
    [
        (OmopDomain.OBSERVATION, "observation"),
        (OmopDomain.MEASUREMENT, "measurement"),
        (OmopDomain.CONDITION, "condition_occurrence"),
        (OmopDomain.NOTE, "note"),
        (OmopDomain.NOTE_NLP, "note_nlp"),
    ],
)
def test_omop_destination_comes_from_concept_domain(
    domain: OmopDomain,
    table: str,
    evidence: EvidenceReference,
) -> None:
    event = ClinicalEvent(
        clinical_event_id=deterministic_uuid("clinical", domain),
        canonical_event_id=deterministic_uuid("canonical", domain),
        establishment_id="site-a",
        patient_pseudonym="p-demo",
        target_domain=domain,
        target_concept_id=2_000_001,
        target_concept_code="DEMO-NKDA",
        target_concept_name="Demo concept",
        target_vocabulary_id="EHRFS_DEMO",
        state=AnswerState.PRESENT,
        value="value",
        occurred_at=datetime(2026, 8, 12, tzinfo=UTC),
        source_value="Q1=value",
        mapping_id="mapping-entry-1",
        mapping_release_id="mapping-1",
        vocabulary_release_id="vocabulary-1",
        evidence=(evidence,),
    )

    assert publish_event(event).table == table
