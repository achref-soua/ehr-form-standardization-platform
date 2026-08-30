"""Immutable mapping-release schema."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from ehrfs.domain.enums import AnswerState, OmopDomain
from ehrfs.domain.identity import content_hash
from ehrfs.domain.models import DomainModel, ScalarValue


class VocabularyRelease(DomainModel):
    release_id: str
    vocabulary_version: str
    source: str
    checksum_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class MappingScope(DomainModel):
    ehr_product: str
    form_family: str
    item_path: str
    source_fingerprint: str | None = None
    compatibility_fingerprint: str | None = None
    establishment_id: str | None = None

    @model_validator(mode="after")
    def validate_fingerprint(self) -> Self:
        if self.source_fingerprint is None and self.compatibility_fingerprint is None:
            msg = "A mapping scope requires an exact source or compatibility fingerprint"
            raise ValueError(msg)
        return self


class MappingTarget(DomainModel):
    domain: OmopDomain
    concept_id: int = Field(gt=0)
    concept_code: str
    concept_name: str
    vocabulary_id: str
    standard_concept: bool


class UnitRule(DomainModel):
    source_unit: str
    target_unit: str
    multiplier: str = "1"
    offset: str = "0"


class MappingTestVector(DomainModel):
    name: str
    source_state: AnswerState
    source_value: ScalarValue | None = None
    source_unit: str | None = None
    expected_state: AnswerState
    expected_value: ScalarValue | None = None
    expected_unit: str | None = None


class MappingEntry(DomainModel):
    mapping_id: str
    scope: MappingScope
    declared_source_type: str
    target: MappingTarget
    value_map: dict[str, ScalarValue] = Field(default_factory=dict)
    state_map: dict[AnswerState, AnswerState] = Field(default_factory=dict)
    unit_rule: UnitRule | None = None
    missing_value_codes: tuple[str, ...] = ()
    negative_value_codes: tuple[str, ...] = ()
    repeated_group_behavior: Literal["single", "preserve-instance", "aggregate"] = "single"
    tests: tuple[MappingTestVector, ...]

    @model_validator(mode="after")
    def require_tests(self) -> Self:
        if not self.tests:
            msg = "Released mapping entries require executable test vectors"
            raise ValueError(msg)
        return self


class MappingReleaseArtifact(DomainModel):
    schema_version: Literal["1.0"] = "1.0"
    release_id: str
    parent_release_id: str | None = None
    vocabulary_release: VocabularyRelease
    entries: tuple[MappingEntry, ...]
    authored_by: str
    approved_by: str
    approved_at: datetime
    payload_checksum_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    signature_base64: str
    signing_key_id: str

    @model_validator(mode="after")
    def enforce_maker_checker(self) -> Self:
        if self.authored_by == self.approved_by:
            msg = "Mapping releases require distinct author and approver identities"
            raise ValueError(msg)
        mapping_ids = [entry.mapping_id for entry in self.entries]
        if len(mapping_ids) != len(set(mapping_ids)):
            msg = "Mapping IDs must be unique within a release"
            raise ValueError(msg)
        return self

    def unsigned_payload(self) -> dict[str, object]:
        payload = self.model_dump(mode="json")
        payload.pop("payload_checksum_sha256")
        payload.pop("signature_base64")
        payload.pop("signing_key_id")
        return payload

    def has_valid_checksum(self) -> bool:
        return content_hash(self.unsigned_payload()) == self.payload_checksum_sha256
