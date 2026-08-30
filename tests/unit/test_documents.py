from ehrfs.documents.assertion import extract_allergy_candidate
from ehrfs.documents.reconciliation import reconcile_structured_and_narrative
from ehrfs.domain.enums import (
    AnswerState,
    ExtractionMethod,
    FailureReason,
    PublicationDecision,
)
from ehrfs.domain.models import EvidenceReference


def _evidence(confidence: float = 0.99) -> EvidenceReference:
    return EvidenceReference(
        object_key="documents/allergy.png",
        checksum_sha256="c" * 64,
        media_type="image/png",
        page=1,
        bounding_box=(10, 20, 300, 80),
        extraction_method=ExtractionMethod.OCR_RULES,
        extractor_version="paddleocr-test",
        confidence=confidence,
    )


def test_positive_allergy_candidate_keeps_substance_reaction_and_evidence() -> None:
    candidate = extract_allergy_candidate(
        "Allergie à la pénicilline avec urticaire.",
        evidence=_evidence(),
    )
    assert candidate.assertion == AnswerState.PRESENT
    assert candidate.substance == "Penicillin"
    assert candidate.reaction == "Urticaria"
    assert not candidate.failures


def test_negative_allergy_is_not_missing() -> None:
    candidate = extract_allergy_candidate("Aucune allergie connue.", evidence=_evidence())
    assert candidate.assertion == AnswerState.EXPLICITLY_ABSENT


def test_uncertain_assertion_abstains() -> None:
    candidate = extract_allergy_candidate(
        "Allergie possible à l'amoxicilline, à confirmer.",
        evidence=_evidence(),
    )
    assert candidate.assertion == AnswerState.UNKNOWN
    assert candidate.failures == (FailureReason.TEXT_ASSERTION_UNCERTAIN,)


def test_low_ocr_confidence_fails_closed() -> None:
    candidate = extract_allergy_candidate(
        "Allergie au latex.",
        evidence=_evidence(0.6),
    )
    assert candidate.failures == (FailureReason.OCR_CONFIDENCE_TOO_LOW,)


def test_structured_narrative_conflict_quarantines_both_evidence_paths() -> None:
    narrative = extract_allergy_candidate(
        "Allergie à la pénicilline.",
        evidence=_evidence(),
    )
    result = reconcile_structured_and_narrative(
        AnswerState.EXPLICITLY_ABSENT,
        structured_evidence=(_evidence().model_copy(update={"object_key": "structured/form"}),),
        narrative=narrative,
    )
    assert result.structured_decision == PublicationDecision.QUARANTINE
    assert result.narrative_decision == PublicationDecision.QUARANTINE
    assert result.failures == (FailureReason.CLINICAL_INCONSISTENCY,)
    assert len(result.evidence) == 2


def test_low_confidence_narrative_does_not_replace_structured_fact() -> None:
    narrative = extract_allergy_candidate("Allergie au latex.", evidence=_evidence(0.6))
    result = reconcile_structured_and_narrative(
        AnswerState.PRESENT,
        structured_evidence=(_evidence(),),
        narrative=narrative,
    )
    assert result.structured_decision == PublicationDecision.PUBLISH
    assert result.narrative_decision == PublicationDecision.QUARANTINE
    assert result.failures == (FailureReason.OCR_CONFIDENCE_TOO_LOW,)


def test_agreeing_narrative_is_corroborating_evidence_not_a_duplicate_fact() -> None:
    narrative = extract_allergy_candidate("Aucune allergie connue.", evidence=_evidence())
    result = reconcile_structured_and_narrative(
        AnswerState.EXPLICITLY_ABSENT,
        structured_evidence=(_evidence(),),
        narrative=narrative,
    )
    assert result.structured_decision == PublicationDecision.PUBLISH
    assert result.narrative_decision == PublicationDecision.OMIT
    assert not result.failures


def test_non_comparable_narrative_state_abstains() -> None:
    narrative = extract_allergy_candidate("Aucune allergie connue.", evidence=_evidence())
    result = reconcile_structured_and_narrative(
        AnswerState.UNKNOWN,
        structured_evidence=(_evidence(),),
        narrative=narrative,
    )
    assert result.narrative_decision == PublicationDecision.QUARANTINE
    assert result.failures == (FailureReason.TEXT_ASSERTION_UNCERTAIN,)
