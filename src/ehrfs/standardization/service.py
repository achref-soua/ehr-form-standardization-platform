"""Apply one exact released mapping to one canonical answer."""

from __future__ import annotations

from ehrfs.domain.enums import AnswerState, FailureReason
from ehrfs.domain.identity import deterministic_uuid
from ehrfs.domain.models import CanonicalAnswerEvent, ScalarValue
from ehrfs.mapping.models import MappingReleaseArtifact
from ehrfs.mapping.resolver import MappingResolver
from ehrfs.standardization.conversion import convert_unit, normalize_source_value
from ehrfs.standardization.models import ClinicalEvent, StandardizationResult


class Standardizer:
    def __init__(self, artifact: MappingReleaseArtifact) -> None:
        self._artifact = artifact
        self._resolver = MappingResolver(artifact)

    def standardize(self, answer: CanonicalAnswerEvent) -> StandardizationResult:
        resolved = self._resolver.resolve(answer)
        if resolved is None:
            return StandardizationResult(
                failures=(FailureReason.UNKNOWN_MAPPING,),
                details=("No exact released mapping matched this answer",),
            )

        entry = resolved.entry
        state = entry.state_map.get(answer.state, answer.state)
        value: ScalarValue | None = answer.value
        unit = answer.unit
        source_value = None if answer.raw_value is None else str(answer.raw_value)

        if answer.state == AnswerState.PRESENT and answer.value is not None:
            normalized = normalize_source_value(answer.value)
            if normalized in entry.missing_value_codes:
                state = AnswerState.UNKNOWN
                value = None
                unit = None
            elif normalized in entry.negative_value_codes:
                state = AnswerState.EXPLICITLY_ABSENT
                value = None
                unit = None
            elif entry.value_map:
                mapped = entry.value_map.get(normalized)
                if mapped is None:
                    return StandardizationResult(
                        failures=(FailureReason.UNKNOWN_LOCAL_VALUE,),
                        details=(f"Local value '{normalized}' is not released",),
                    )
                value = mapped
            if state == AnswerState.PRESENT and entry.unit_rule is not None:
                if answer.unit != entry.unit_rule.source_unit:
                    return StandardizationResult(
                        failures=(FailureReason.INVALID_UNIT,),
                        details=(
                            f"Expected {entry.unit_rule.source_unit}; "
                            f"received {answer.unit or 'none'}",
                        ),
                    )
                try:
                    value = convert_unit(answer.value, entry.unit_rule)
                except (TypeError, ValueError) as error:
                    return StandardizationResult(
                        failures=(FailureReason.INVALID_UNIT,),
                        details=(str(error),),
                    )
                unit = entry.unit_rule.target_unit

        if state != AnswerState.PRESENT:
            value = None
            unit = None

        clinical_event_id = deterministic_uuid(
            "clinical-event",
            str(answer.event_id),
            resolved.release_id,
            entry.mapping_id,
        )
        event = ClinicalEvent(
            clinical_event_id=clinical_event_id,
            canonical_event_id=answer.event_id,
            establishment_id=answer.establishment_id,
            patient_pseudonym=answer.patient_pseudonym,
            encounter_pseudonym=answer.encounter_pseudonym,
            occurred_at=answer.authored_at,
            state=state,
            value=value,
            unit=unit,
            target_domain=entry.target.domain,
            target_concept_id=entry.target.concept_id,
            target_concept_code=entry.target.concept_code,
            target_concept_name=entry.target.concept_name,
            target_vocabulary_id=entry.target.vocabulary_id,
            source_value=source_value,
            mapping_id=entry.mapping_id,
            mapping_release_id=resolved.release_id,
            vocabulary_release_id=self._artifact.vocabulary_release.release_id,
            evidence=answer.evidence,
        )
        return StandardizationResult(event=event)
