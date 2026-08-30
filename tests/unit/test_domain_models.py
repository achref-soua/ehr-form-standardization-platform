from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ehrfs.domain.enums import AnswerState, ExtractionMethod, LifecycleStatus
from ehrfs.domain.models import (
    CanonicalAnswerEvent,
    DisplayCondition,
    EvidenceReference,
    LifecycleEvent,
)


def test_present_answer_requires_a_value(evidence: EvidenceReference) -> None:
    with pytest.raises(ValidationError, match="PRESENT answers require"):
        CanonicalAnswerEvent(
            event_id=uuid4(),
            establishment_id="site-a",
            patient_pseudonym="p_123",
            form_id="form",
            form_version="1",
            source_fingerprint="source",
            compatibility_fingerprint="compatibility",
            item_path="Q1",
            state=AnswerState.PRESENT,
            authored_at=datetime.now(UTC),
            evidence=(evidence,),
        )


@pytest.mark.parametrize(
    "state",
    [
        AnswerState.EXPLICITLY_ABSENT,
        AnswerState.UNKNOWN,
        AnswerState.NOT_RECORDED,
        AnswerState.NOT_APPLICABLE,
        AnswerState.NOT_DISPLAYED_BY_FORM_LOGIC,
        AnswerState.VOIDED,
        AnswerState.SUPERSEDED,
        AnswerState.DELETED,
    ],
)
def test_non_present_answers_reject_typed_values(
    state: AnswerState,
    evidence: EvidenceReference,
) -> None:
    with pytest.raises(ValidationError, match="cannot carry a typed value"):
        CanonicalAnswerEvent(
            event_id=uuid4(),
            establishment_id="site-a",
            patient_pseudonym="p_123",
            form_id="form",
            form_version="1",
            source_fingerprint="source",
            compatibility_fingerprint="compatibility",
            item_path="Q1",
            state=state,
            value="unexpected",
            authored_at=datetime.now(UTC),
            evidence=(evidence,),
        )


def test_canonical_event_requires_evidence() -> None:
    with pytest.raises(ValidationError, match="require source evidence"):
        CanonicalAnswerEvent(
            event_id=uuid4(),
            establishment_id="site-a",
            patient_pseudonym="p_123",
            form_id="form",
            form_version="1",
            source_fingerprint="source",
            compatibility_fingerprint="compatibility",
            item_path="Q1",
            state=AnswerState.NOT_RECORDED,
            authored_at=datetime.now(UTC),
            evidence=(),
        )


def test_correction_requires_superseded_event() -> None:
    with pytest.raises(ValidationError, match="require a superseded event"):
        LifecycleEvent(
            status=LifecycleStatus.CORRECTED,
            occurred_at=datetime.now(UTC),
            source_sequence=2,
        )


def test_evidence_rejects_partial_text_span() -> None:
    with pytest.raises(ValidationError, match="provided together"):
        EvidenceReference(
            object_key="document.pdf",
            checksum_sha256="b" * 64,
            media_type="application/pdf",
            text_span_start=10,
            extraction_method=ExtractionMethod.NATIVE_TEXT,
            extractor_version="test",
        )


def test_exists_condition_requires_boolean() -> None:
    with pytest.raises(ValidationError, match="requires a boolean"):
        DisplayCondition(source_item_path="Q1", operator="exists", expected="yes")
