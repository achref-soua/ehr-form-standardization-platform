"""Deterministic structured/narrative evidence reconciliation with abstention."""

from __future__ import annotations

from ehrfs.documents.models import DocumentCandidate
from ehrfs.domain.enums import AnswerState, FailureReason, PublicationDecision
from ehrfs.domain.models import DomainModel, EvidenceReference

COMPARABLE_STATES = frozenset({AnswerState.PRESENT, AnswerState.EXPLICITLY_ABSENT})


class ReconciliationResult(DomainModel):
    structured_decision: PublicationDecision
    narrative_decision: PublicationDecision
    failures: tuple[FailureReason, ...]
    evidence: tuple[EvidenceReference, ...]


def reconcile_structured_and_narrative(
    structured_state: AnswerState,
    *,
    structured_evidence: tuple[EvidenceReference, ...],
    narrative: DocumentCandidate,
) -> ReconciliationResult:
    """Keep uncertain extraction separate and quarantine explicit cross-source conflicts."""
    evidence = (*structured_evidence, narrative.evidence)
    if narrative.failures:
        return ReconciliationResult(
            structured_decision=PublicationDecision.PUBLISH,
            narrative_decision=PublicationDecision.QUARANTINE,
            failures=narrative.failures,
            evidence=evidence,
        )
    if structured_state in COMPARABLE_STATES and narrative.assertion in COMPARABLE_STATES:
        if structured_state != narrative.assertion:
            return ReconciliationResult(
                structured_decision=PublicationDecision.QUARANTINE,
                narrative_decision=PublicationDecision.QUARANTINE,
                failures=(FailureReason.CLINICAL_INCONSISTENCY,),
                evidence=evidence,
            )
        return ReconciliationResult(
            structured_decision=PublicationDecision.PUBLISH,
            narrative_decision=PublicationDecision.OMIT,
            failures=(),
            evidence=evidence,
        )
    return ReconciliationResult(
        structured_decision=PublicationDecision.PUBLISH,
        narrative_decision=PublicationDecision.QUARANTINE,
        failures=(FailureReason.TEXT_ASSERTION_UNCERTAIN,),
        evidence=evidence,
    )
