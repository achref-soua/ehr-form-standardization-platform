"""Project clinical events into supported OMOP 5.4 domains."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import model_validator

from ehrfs.domain.enums import AnswerState, OmopDomain
from ehrfs.domain.identity import deterministic_uuid
from ehrfs.domain.models import DomainModel
from ehrfs.standardization.models import ClinicalEvent

OmopTable = Literal["condition_occurrence", "measurement", "observation", "note", "note_nlp"]


class OmopFact(DomainModel):
    fact_id: UUID
    table: OmopTable
    person_source_value: str
    concept_id: int
    event_date: date
    event_datetime: datetime
    value_as_number: Decimal | None = None
    value_as_string: str | None = None
    value_as_concept_id: int | None = None
    unit_source_value: str | None = None
    source_value: str | None = None
    clinical_event_id: UUID

    @model_validator(mode="after")
    def validate_value_columns(self) -> Self:
        values = [self.value_as_number, self.value_as_string, self.value_as_concept_id]
        if sum(value is not None for value in values) > 1:
            msg = "OMOP facts may populate at most one value column"
            raise ValueError(msg)
        return self


TABLE_BY_DOMAIN: dict[OmopDomain, OmopTable] = {
    OmopDomain.CONDITION: "condition_occurrence",
    OmopDomain.MEASUREMENT: "measurement",
    OmopDomain.OBSERVATION: "observation",
    OmopDomain.NOTE: "note",
    OmopDomain.NOTE_NLP: "note_nlp",
}


def publish_event(event: ClinicalEvent) -> OmopFact:
    table = TABLE_BY_DOMAIN[event.target_domain]
    value_as_number: Decimal | None = None
    value_as_string: str | None = None
    value_as_concept_id: int | None = None
    if event.state == AnswerState.PRESENT and event.value is not None:
        if isinstance(event.value, bool):
            value_as_string = "true" if event.value else "false"
        elif isinstance(event.value, (int, float, Decimal)):
            value_as_number = Decimal(str(event.value))
        else:
            value_as_string = str(event.value)
    elif event.state == AnswerState.EXPLICITLY_ABSENT:
        value_as_string = AnswerState.EXPLICITLY_ABSENT
    fact_id = deterministic_uuid(
        "omop-fact",
        table,
        str(event.clinical_event_id),
        str(event.target_concept_id),
    )
    return OmopFact(
        fact_id=fact_id,
        table=table,
        person_source_value=event.patient_pseudonym,
        concept_id=event.target_concept_id,
        event_date=event.occurred_at.date(),
        event_datetime=event.occurred_at,
        value_as_number=value_as_number,
        value_as_string=value_as_string,
        value_as_concept_id=value_as_concept_id,
        unit_source_value=event.unit,
        source_value=event.source_value,
        clinical_event_id=event.clinical_event_id,
    )
