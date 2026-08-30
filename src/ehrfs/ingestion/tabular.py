"""Bounded tabular/EAV adapter for explicit source schemas."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ehrfs.canonical.state import derive_answer_state
from ehrfs.domain.enums import AnswerState, LifecycleStatus
from ehrfs.domain.identity import deterministic_uuid
from ehrfs.domain.models import CanonicalAnswerEvent, EvidenceReference, FormDefinition, ScalarValue
from ehrfs.fingerprinting.service import fingerprint_form


@dataclass(frozen=True, slots=True)
class TabularAnswer:
    response_id: str
    patient_pseudonym: str
    item_path: str
    raw_value: ScalarValue | None
    authored_at: datetime
    lifecycle_status: LifecycleStatus = LifecycleStatus.SIGNED
    group_instance: str | None = None
    unit: str | None = None


class TabularFormAdapter:
    connector_version = "tabular-eav/1.0.0"

    def canonicalize(
        self,
        definition: FormDefinition,
        answers: tuple[TabularAnswer, ...],
        *,
        establishment_id: str,
        evidence: EvidenceReference,
    ) -> tuple[CanonicalAnswerEvent, ...]:
        fingerprints = fingerprint_form(definition)
        events: list[CanonicalAnswerEvent] = []
        for answer in answers:
            state = derive_answer_state(
                response_present=True,
                enabled=True,
                raw_value=answer.raw_value,
                lifecycle_status=answer.lifecycle_status,
            )
            events.append(
                CanonicalAnswerEvent(
                    event_id=deterministic_uuid(
                        "canonical-answer",
                        establishment_id,
                        answer.response_id,
                        answer.item_path,
                        answer.group_instance or "0",
                    ),
                    establishment_id=establishment_id,
                    patient_pseudonym=answer.patient_pseudonym,
                    form_id=definition.form_id,
                    form_version=definition.version,
                    source_fingerprint=fingerprints.source,
                    compatibility_fingerprint=fingerprints.compatibility,
                    item_path=answer.item_path,
                    group_instance=answer.group_instance,
                    state=state,
                    value=answer.raw_value if state == AnswerState.PRESENT else None,
                    raw_value=answer.raw_value,
                    unit=answer.unit,
                    authored_at=answer.authored_at,
                    evidence=(evidence,),
                )
            )
        return tuple(events)
