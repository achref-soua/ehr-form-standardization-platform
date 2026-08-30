"""Immutable domain models and invariants."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ehrfs.domain.enums import AnswerState, ExtractionMethod, LifecycleStatus

ScalarValue = str | int | float | bool | Decimal | date | datetime


class DomainModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", ser_json_timedelta="iso8601")


class ValueOption(DomainModel):
    code: str
    display: str
    system: str | None = None


class DisplayCondition(DomainModel):
    source_item_path: str
    operator: Literal["eq", "ne", "gt", "gte", "lt", "lte", "exists"]
    expected: ScalarValue | None = None

    @model_validator(mode="after")
    def validate_expected_value(self) -> Self:
        if self.operator == "exists" and not isinstance(self.expected, bool):
            msg = "The exists operator requires a boolean expected value"
            raise ValueError(msg)
        if self.operator != "exists" and self.expected is None:
            msg = "Comparison operators require an expected value"
            raise ValueError(msg)
        return self


class ItemDefinition(DomainModel):
    item_id: str
    path: str
    label: str
    data_type: Literal[
        "boolean", "integer", "decimal", "string", "text", "date", "datetime", "coding", "group"
    ]
    order: int
    order_semantic: bool = True
    required: bool = False
    repeats: bool = False
    unit: str | None = None
    value_options: tuple[ValueOption, ...] = ()
    display_conditions: tuple[DisplayCondition, ...] = ()
    children: tuple[ItemDefinition, ...] = ()
    calculation: str | None = None

    @model_validator(mode="after")
    def validate_item_shape(self) -> Self:
        if self.data_type == "group" and not self.children:
            msg = "Group items require children"
            raise ValueError(msg)
        if self.data_type != "group" and self.children:
            msg = "Only group items may contain children"
            raise ValueError(msg)
        paths = [child.path for child in self.children]
        if len(paths) != len(set(paths)):
            msg = "Child item paths must be unique"
            raise ValueError(msg)
        return self


class FormDefinition(DomainModel):
    ehr_product: str
    ehr_version: str
    form_id: str
    form_family: str
    version: str
    title: str
    items: tuple[ItemDefinition, ...]
    source_order_semantic: bool = True
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_paths(self) -> Self:
        all_paths: list[str] = []

        def collect(items: tuple[ItemDefinition, ...]) -> None:
            for item in items:
                all_paths.append(item.path)
                collect(item.children)

        collect(self.items)
        if len(all_paths) != len(set(all_paths)):
            msg = "Every item path in a form definition must be unique"
            raise ValueError(msg)
        return self


class EvidenceReference(DomainModel):
    object_key: str
    checksum_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    media_type: str
    json_pointer: str | None = None
    source_locator: str | None = None
    page: int | None = Field(default=None, ge=1)
    text_span_start: int | None = Field(default=None, ge=0)
    text_span_end: int | None = Field(default=None, ge=0)
    bounding_box: tuple[float, float, float, float] | None = None
    extraction_method: ExtractionMethod
    extractor_version: str
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_span(self) -> Self:
        if (self.text_span_start is None) != (self.text_span_end is None):
            msg = "Text span start and end must be provided together"
            raise ValueError(msg)
        if (
            self.text_span_start is not None
            and self.text_span_end is not None
            and self.text_span_end <= self.text_span_start
        ):
            msg = "Text span end must be greater than its start"
            raise ValueError(msg)
        return self


class LifecycleEvent(DomainModel):
    status: LifecycleStatus
    occurred_at: datetime
    source_sequence: int = Field(ge=0)
    supersedes_event_id: UUID | None = None

    @model_validator(mode="after")
    def validate_supersession(self) -> Self:
        needs_reference = self.status in {LifecycleStatus.CORRECTED, LifecycleStatus.VOIDED}
        if needs_reference and self.supersedes_event_id is None:
            msg = f"{self.status} lifecycle events require a superseded event"
            raise ValueError(msg)
        return self


class SourceManifest(DomainModel):
    manifest_id: UUID
    establishment_id: str
    source_system_id: str
    batch_id: str
    source_period_start: date
    source_period_end: date
    object_keys: tuple[str, ...]
    object_checksums: tuple[Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")], ...]
    record_count: int = Field(ge=0)
    connector_version: str
    schema_version: str
    created_at: datetime

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        if len(self.object_keys) != len(self.object_checksums):
            msg = "Every source object must have exactly one checksum"
            raise ValueError(msg)
        if self.source_period_end < self.source_period_start:
            msg = "Source period end cannot precede its start"
            raise ValueError(msg)
        return self


class CanonicalAnswerEvent(DomainModel):
    event_id: UUID
    establishment_id: str
    patient_pseudonym: str
    encounter_pseudonym: str | None = None
    form_id: str
    form_version: str
    source_fingerprint: str
    compatibility_fingerprint: str
    item_path: str
    group_instance: str | None = None
    state: AnswerState
    value: ScalarValue | None = None
    raw_value: Any | None = None
    unit: str | None = None
    authored_at: datetime
    lifecycle: tuple[LifecycleEvent, ...] = ()
    evidence: tuple[EvidenceReference, ...]

    @model_validator(mode="after")
    def validate_state_value_and_evidence(self) -> Self:
        if self.state == AnswerState.PRESENT and self.value is None:
            msg = "PRESENT answers require a typed value"
            raise ValueError(msg)
        if self.state not in {AnswerState.PRESENT, AnswerState.INVALID} and self.value is not None:
            msg = f"{self.state} answers cannot carry a typed value"
            raise ValueError(msg)
        if not self.evidence:
            msg = "Canonical answer events require source evidence"
            raise ValueError(msg)
        return self


def utc_now() -> datetime:
    """Return an aware UTC timestamp through a patchable boundary."""
    return datetime.now(UTC)
