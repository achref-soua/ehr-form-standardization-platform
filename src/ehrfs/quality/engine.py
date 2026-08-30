"""Deterministic publication decision engine."""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from ehrfs.domain.enums import (
    AnswerState,
    FailureReason,
    PublicationDecision,
    QualitySeverity,
)
from ehrfs.domain.identity import deterministic_uuid
from ehrfs.domain.models import CanonicalAnswerEvent
from ehrfs.quality.models import QualityResult
from ehrfs.standardization.models import StandardizationResult


class QualityDecision(StandardizationResult):
    decision: PublicationDecision
    results: tuple[QualityResult, ...]


class QualityEngine:
    RULE_VERSION = "1.0.0"
    OMIT_STATES: ClassVar[frozenset[AnswerState]] = frozenset(
        {
            AnswerState.NOT_RECORDED,
            AnswerState.NOT_APPLICABLE,
            AnswerState.NOT_DISPLAYED_BY_FORM_LOGIC,
            AnswerState.VOIDED,
            AnswerState.SUPERSEDED,
            AnswerState.DELETED,
        }
    )

    def evaluate(
        self,
        canonical: CanonicalAnswerEvent,
        standardized: StandardizationResult,
        *,
        evaluated_at: datetime,
    ) -> QualityDecision:
        results: list[QualityResult] = []

        def add(
            rule_id: str,
            passed: bool,
            message: str,
            reason: FailureReason | None = None,
        ) -> None:
            results.append(
                QualityResult(
                    result_id=deterministic_uuid(
                        "quality-result",
                        str(canonical.event_id),
                        rule_id,
                        self.RULE_VERSION,
                    ),
                    clinical_event_id=(
                        standardized.event.clinical_event_id if standardized.event else None
                    ),
                    canonical_event_id=canonical.event_id,
                    rule_id=rule_id,
                    rule_version=self.RULE_VERSION,
                    passed=passed,
                    severity=QualitySeverity.INFO if passed else QualitySeverity.ERROR,
                    reason=reason,
                    message=message,
                    evaluated_at=evaluated_at,
                )
            )

        add(
            "provenance.evidence-present",
            bool(canonical.evidence),
            "Source evidence is present" if canonical.evidence else "Source evidence is missing",
            None if canonical.evidence else FailureReason.MISSING_PROVENANCE,
        )
        mapping_required = canonical.state not in self.OMIT_STATES
        mapping_resolved = standardized.event is not None or not mapping_required
        add(
            "mapping.resolved",
            mapping_resolved,
            (
                "A released mapping resolved"
                if standardized.event
                else (
                    "Mapping is not required for an omitted answer state"
                    if not mapping_required
                    else "No released mapping resolved"
                )
            ),
            (
                None
                if mapping_resolved
                else (
                    standardized.failures[0]
                    if standardized.failures
                    else FailureReason.UNKNOWN_MAPPING
                )
            ),
        )
        state_publishable = canonical.state not in {
            AnswerState.INVALID,
            AnswerState.VOIDED,
            AnswerState.SUPERSEDED,
            AnswerState.DELETED,
        }
        add(
            "lifecycle.publishable",
            state_publishable,
            f"Canonical answer state is {canonical.state}",
            None if state_publishable else FailureReason.CLINICAL_INCONSISTENCY,
        )
        if standardized.event is not None:
            standard_concept = standardized.event.target_concept_id > 0
            add(
                "omop.standard-concept",
                standard_concept,
                "Target concept is populated",
                None if standard_concept else FailureReason.OMOP_CONFORMANCE_FAILURE,
            )

        failures = tuple(
            result.reason for result in results if not result.passed and result.reason is not None
        )
        if canonical.state in self.OMIT_STATES:
            decision = PublicationDecision.OMIT
        elif failures:
            decision = PublicationDecision.QUARANTINE
        else:
            decision = PublicationDecision.PUBLISH
        return QualityDecision(
            event=standardized.event,
            failures=failures,
            details=tuple(result.message for result in results if not result.passed),
            decision=decision,
            results=tuple(results),
        )
