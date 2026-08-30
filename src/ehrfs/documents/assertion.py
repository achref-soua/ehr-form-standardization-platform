"""Bounded French allergy assertion rules with mandatory abstention."""

from __future__ import annotations

import re

from ehrfs.documents.models import DocumentCandidate
from ehrfs.domain.enums import AnswerState, ExtractionMethod, FailureReason
from ehrfs.domain.models import EvidenceReference

ALLERGY_SECTION = re.compile(r"\b(?:allerg(?:ie|ies|ique)|hypersensibilit[ée])\b", re.IGNORECASE)
NEGATION = re.compile(
    r"\b(?:aucune?|sans|absence\s+d['\u2019]?|pas\s+d['\u2019]?)\s+(?:allergie|allergies)\b",
    re.IGNORECASE,
)
UNCERTAINTY = re.compile(
    r"\b(?:possible|suspect(?:e|ée)?|à\s+confirmer|incertain(?:e)?)\b",
    re.IGNORECASE,
)
SUBSTANCES = {
    "penicilline": "Penicillin",
    "pénicilline": "Penicillin",
    "amoxicilline": "Amoxicillin",
    "latex": "Latex",
}
REACTIONS = {
    "urticaire": "Urticaria",
    "anaphylaxie": "Anaphylaxis",
    "éruption": "Rash",
    "eruption": "Rash",
}


def _first_dictionary_match(text: str, values: dict[str, str]) -> str | None:
    folded = text.casefold()
    return next((target for source, target in values.items() if source in folded), None)


def extract_allergy_candidate(
    text: str,
    *,
    evidence: EvidenceReference,
    minimum_confidence: float = 0.85,
) -> DocumentCandidate:
    normalized = " ".join(text.split())
    if not ALLERGY_SECTION.search(normalized):
        return DocumentCandidate(
            concept="allergy history",
            assertion=AnswerState.UNKNOWN,
            confidence=0,
            method=evidence.extraction_method,
            evidence=evidence,
            failures=(FailureReason.TEXT_ASSERTION_UNCERTAIN,),
        )
    if UNCERTAINTY.search(normalized):
        confidence = min(evidence.confidence or 0.7, 0.7)
        return DocumentCandidate(
            concept="allergy history",
            substance=_first_dictionary_match(normalized, SUBSTANCES),
            reaction=_first_dictionary_match(normalized, REACTIONS),
            assertion=AnswerState.UNKNOWN,
            confidence=confidence,
            method=evidence.extraction_method,
            evidence=evidence,
            failures=(FailureReason.TEXT_ASSERTION_UNCERTAIN,),
        )
    assertion = (
        AnswerState.EXPLICITLY_ABSENT if NEGATION.search(normalized) else AnswerState.PRESENT
    )
    confidence = evidence.confidence if evidence.confidence is not None else 1.0
    failures = (
        (FailureReason.OCR_CONFIDENCE_TOO_LOW,)
        if evidence.extraction_method == ExtractionMethod.OCR_RULES
        and confidence < minimum_confidence
        else ()
    )
    return DocumentCandidate(
        concept="allergy history",
        substance=_first_dictionary_match(normalized, SUBSTANCES),
        reaction=_first_dictionary_match(normalized, REACTIONS),
        assertion=assertion,
        confidence=confidence,
        method=evidence.extraction_method,
        evidence=evidence,
        failures=failures,
    )
