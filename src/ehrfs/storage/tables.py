"""Relational control-plane, audit, and supported official OMOP table mappings."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSONB}


class EstablishmentRow(Base):
    __tablename__ = "establishment"
    __table_args__ = {"schema": "control"}

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    region: Mapped[str] = mapped_column(String(100), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class SourceSystemRow(Base):
    __tablename__ = "source_system"
    __table_args__ = (
        UniqueConstraint("establishment_id", "source_key", name="uq_source_site_key"),
        {"schema": "control"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    establishment_id: Mapped[str] = mapped_column(
        ForeignKey("control.establishment.id"), nullable=False
    )
    source_key: Mapped[str] = mapped_column(String(100), nullable=False)
    family: Mapped[str] = mapped_column(String(50), nullable=False)
    version: Mapped[str] = mapped_column(String(100), nullable=False)


class FormVersionRow(Base):
    __tablename__ = "form_version"
    __table_args__ = (
        UniqueConstraint("establishment_id", "form_id", "version", name="uq_form_site_version"),
        Index("ix_form_source_fingerprint", "source_fingerprint"),
        {"schema": "control"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    establishment_id: Mapped[str] = mapped_column(
        ForeignKey("control.establishment.id"), nullable=False
    )
    form_id: Mapped[str] = mapped_column(String(200), nullable=False)
    family: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    compatibility_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    definition_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    mapping_status: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MappingDraftRow(Base):
    __tablename__ = "mapping_draft"
    __table_args__ = {"schema": "control"}

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    form_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("control.form_version.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    authored_by: Mapped[str] = mapped_column(String(200), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(200))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MappingReleaseRow(Base):
    __tablename__ = "mapping_release"
    __table_args__ = {"schema": "control"}

    release_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    parent_release_id: Mapped[str | None] = mapped_column(String(100))
    artifact_object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    signature_base64: Mapped[str] = mapped_column(Text, nullable=False)
    signing_key_id: Mapped[str] = mapped_column(String(32), nullable=False)
    authored_by: Mapped[str] = mapped_column(String(200), nullable=False)
    approved_by: Mapped[str] = mapped_column(String(200), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PipelineJobRow(Base):
    __tablename__ = "pipeline_job"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_pipeline_job_idempotency"),
        Index("ix_pipeline_job_claim", "status", "available_at", "created_at"),
        {"schema": "control"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(100), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    maximum_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    leased_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    leased_by: Mapped[str | None] = mapped_column(String(200))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class WorkerHeartbeatRow(Base):
    __tablename__ = "worker_heartbeat"
    __table_args__ = {"schema": "control"}

    worker_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    build_version: Mapped[str] = mapped_column(String(50), nullable=False)


class QuarantineRow(Base):
    __tablename__ = "quarantine_record"
    __table_args__ = (
        Index("ix_quarantine_reason_status", "reason", "status"),
        {"schema": "control"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    job_id: Mapped[UUID] = mapped_column(ForeignKey("control.pipeline_job.id"), nullable=False)
    establishment_id: Mapped[str] = mapped_column(String(100), nullable=False)
    form_id: Mapped[str] = mapped_column(String(200), nullable=False)
    item_path: Mapped[str | None] = mapped_column(String(500))
    reason: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    context_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ResearchReleaseRow(Base):
    __tablename__ = "research_release"
    __table_args__ = {"schema": "control"}

    release_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    parent_release_id: Mapped[str | None] = mapped_column(String(100))
    mapping_release_id: Mapped[str] = mapped_column(String(100), nullable=False)
    artifact_object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    published_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    quarantined_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class VocabularyImportRow(Base):
    __tablename__ = "vocabulary_import"
    __table_args__ = {"schema": "control"}

    release_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    vocabulary_version: Mapped[str] = mapped_column(String(255), nullable=False)
    source_checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    source_manifest_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    concept_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    standard_concept_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    loaded_by: Mapped[str] = mapped_column(String(200), nullable=False)
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CatalogConceptRow(Base):
    __tablename__ = "catalog_concept"
    __table_args__ = {"schema": "control"}

    concept_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(500), nullable=False)
    definition: Mapped[str] = mapped_column(Text, nullable=False)
    vocabulary_id: Mapped[str] = mapped_column(String(50), nullable=False)
    concept_code: Mapped[str] = mapped_column(String(100), nullable=False)
    limitations: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CoverageMetricRow(Base):
    __tablename__ = "coverage_metric"
    __table_args__ = (
        UniqueConstraint(
            "concept_key",
            "establishment_id",
            "period_start",
            "period_end",
            "research_release_id",
            name="uq_coverage_slice",
        ),
        {"schema": "control"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    concept_key: Mapped[str] = mapped_column(
        ForeignKey("control.catalog_concept.concept_key"), nullable=False
    )
    establishment_id: Mapped[str] = mapped_column(
        ForeignKey("control.establishment.id"), nullable=False
    )
    research_release_id: Mapped[str] = mapped_column(
        ForeignKey("control.research_release.release_id"), nullable=False
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    eligible_count: Mapped[int | None] = mapped_column(BigInteger)
    recorded_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    usable_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    positive_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    completion: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    usable_coverage: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    prevalence: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    method: Mapped[str] = mapped_column(String(100), nullable=False)
    quality_status: Mapped[str] = mapped_column(String(50), nullable=False)


class LineageGraphRow(Base):
    __tablename__ = "lineage_graph"
    __table_args__ = {"schema": "control"}

    root_node_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    graph_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditEventRow(Base):
    __tablename__ = "audit_event"
    __table_args__ = (
        Index("ix_audit_occurred_at", "occurred_at"),
        {"schema": "audit"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(200), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(200), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(100), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class OmopConceptRow(Base):
    __tablename__ = "concept"
    __table_args__ = {"schema": "omop"}

    concept_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    concept_name: Mapped[str] = mapped_column(String(255), nullable=False)
    domain_id: Mapped[str] = mapped_column(String(20), nullable=False)
    vocabulary_id: Mapped[str] = mapped_column(String(20), nullable=False)
    concept_class_id: Mapped[str] = mapped_column(String(20), nullable=False)
    standard_concept: Mapped[str | None] = mapped_column(String(1))
    concept_code: Mapped[str] = mapped_column(String(50), nullable=False)
    valid_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    valid_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    invalid_reason: Mapped[str | None] = mapped_column(String(1))


class OmopVocabularyRow(Base):
    __tablename__ = "vocabulary"
    __table_args__ = {"schema": "omop"}

    vocabulary_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    vocabulary_name: Mapped[str] = mapped_column(String(255), nullable=False)
    vocabulary_reference: Mapped[str | None] = mapped_column(String(255))
    vocabulary_version: Mapped[str | None] = mapped_column(String(255))
    vocabulary_concept_id: Mapped[int] = mapped_column(Integer, nullable=False)


class OmopDomainRow(Base):
    __tablename__ = "domain"
    __table_args__ = {"schema": "omop"}

    domain_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    domain_name: Mapped[str] = mapped_column(String(255), nullable=False)
    domain_concept_id: Mapped[int] = mapped_column(Integer, nullable=False)


class OmopConceptClassRow(Base):
    __tablename__ = "concept_class"
    __table_args__ = {"schema": "omop"}

    concept_class_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    concept_class_name: Mapped[str] = mapped_column(String(255), nullable=False)
    concept_class_concept_id: Mapped[int] = mapped_column(Integer, nullable=False)


class OmopPersonRow(Base):
    __tablename__ = "person"
    __table_args__ = {"schema": "omop"}

    person_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gender_concept_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    year_of_birth: Mapped[int] = mapped_column(Integer, nullable=False)
    month_of_birth: Mapped[int | None] = mapped_column(Integer)
    day_of_birth: Mapped[int | None] = mapped_column(Integer)
    birth_datetime: Mapped[datetime | None] = mapped_column(DateTime)
    race_concept_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ethnicity_concept_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    location_id: Mapped[int | None] = mapped_column(Integer)
    provider_id: Mapped[int | None] = mapped_column(Integer)
    care_site_id: Mapped[int | None] = mapped_column(Integer)
    person_source_value: Mapped[str | None] = mapped_column(String(50))
    gender_source_value: Mapped[str | None] = mapped_column(String(50))
    gender_source_concept_id: Mapped[int | None] = mapped_column(Integer)
    race_source_value: Mapped[str | None] = mapped_column(String(50))
    race_source_concept_id: Mapped[int | None] = mapped_column(Integer)
    ethnicity_source_value: Mapped[str | None] = mapped_column(String(50))
    ethnicity_source_concept_id: Mapped[int | None] = mapped_column(Integer)


class OmopObservationRow(Base):
    __tablename__ = "observation"
    __table_args__ = {"schema": "omop"}

    observation_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("omop.person.person_id"), nullable=False)
    observation_concept_id: Mapped[int] = mapped_column(Integer, nullable=False)
    observation_date: Mapped[date] = mapped_column(Date, nullable=False)
    observation_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observation_type_concept_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    value_as_number: Mapped[Decimal | None] = mapped_column(Numeric)
    value_as_string: Mapped[str | None] = mapped_column(String(60))
    value_as_concept_id: Mapped[int | None] = mapped_column(Integer)
    qualifier_concept_id: Mapped[int | None] = mapped_column(Integer)
    unit_concept_id: Mapped[int | None] = mapped_column(Integer)
    provider_id: Mapped[int | None] = mapped_column(Integer)
    visit_occurrence_id: Mapped[int | None] = mapped_column(Integer)
    visit_detail_id: Mapped[int | None] = mapped_column(Integer)
    observation_source_value: Mapped[str | None] = mapped_column(String(50))
    observation_source_concept_id: Mapped[int | None] = mapped_column(Integer)
    unit_source_value: Mapped[str | None] = mapped_column(String(50))
    qualifier_source_value: Mapped[str | None] = mapped_column(String(50))
    value_source_value: Mapped[str | None] = mapped_column(String(50))
    observation_event_id: Mapped[int | None] = mapped_column(Integer)
    obs_event_field_concept_id: Mapped[int | None] = mapped_column(Integer)


class OmopMeasurementRow(Base):
    __tablename__ = "measurement"
    __table_args__ = {"schema": "omop"}

    measurement_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("omop.person.person_id"), nullable=False)
    measurement_concept_id: Mapped[int] = mapped_column(Integer, nullable=False)
    measurement_date: Mapped[date] = mapped_column(Date, nullable=False)
    measurement_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    measurement_time: Mapped[str | None] = mapped_column(String(10))
    measurement_type_concept_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    operator_concept_id: Mapped[int | None] = mapped_column(Integer)
    value_as_number: Mapped[Decimal | None] = mapped_column(Numeric)
    value_as_concept_id: Mapped[int | None] = mapped_column(Integer)
    unit_concept_id: Mapped[int | None] = mapped_column(Integer)
    range_low: Mapped[Decimal | None] = mapped_column(Numeric)
    range_high: Mapped[Decimal | None] = mapped_column(Numeric)
    provider_id: Mapped[int | None] = mapped_column(Integer)
    visit_occurrence_id: Mapped[int | None] = mapped_column(Integer)
    visit_detail_id: Mapped[int | None] = mapped_column(Integer)
    measurement_source_value: Mapped[str | None] = mapped_column(String(50))
    measurement_source_concept_id: Mapped[int | None] = mapped_column(Integer)
    unit_source_value: Mapped[str | None] = mapped_column(String(50))
    unit_source_concept_id: Mapped[int | None] = mapped_column(Integer)
    value_source_value: Mapped[str | None] = mapped_column(String(50))
    measurement_event_id: Mapped[int | None] = mapped_column(Integer)
    meas_event_field_concept_id: Mapped[int | None] = mapped_column(Integer)


class OmopConditionOccurrenceRow(Base):
    __tablename__ = "condition_occurrence"
    __table_args__ = {"schema": "omop"}

    condition_occurrence_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("omop.person.person_id"), nullable=False)
    condition_concept_id: Mapped[int] = mapped_column(Integer, nullable=False)
    condition_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    condition_start_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    condition_end_date: Mapped[date | None] = mapped_column(Date)
    condition_end_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    condition_type_concept_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    condition_status_concept_id: Mapped[int | None] = mapped_column(Integer)
    stop_reason: Mapped[str | None] = mapped_column(String(20))
    provider_id: Mapped[int | None] = mapped_column(Integer)
    visit_occurrence_id: Mapped[int | None] = mapped_column(Integer)
    visit_detail_id: Mapped[int | None] = mapped_column(Integer)
    condition_source_value: Mapped[str | None] = mapped_column(String(50))
    condition_source_concept_id: Mapped[int | None] = mapped_column(Integer)
    condition_status_source_value: Mapped[str | None] = mapped_column(String(50))


class OmopNoteRow(Base):
    __tablename__ = "note"
    __table_args__ = {"schema": "omop"}

    note_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("omop.person.person_id"), nullable=False)
    note_date: Mapped[date] = mapped_column(Date, nullable=False)
    note_datetime: Mapped[datetime | None] = mapped_column(DateTime)
    note_type_concept_id: Mapped[int] = mapped_column(Integer, nullable=False)
    note_class_concept_id: Mapped[int] = mapped_column(Integer, nullable=False)
    note_title: Mapped[str | None] = mapped_column(String(250))
    note_text: Mapped[str] = mapped_column(Text, nullable=False)
    encoding_concept_id: Mapped[int] = mapped_column(Integer, nullable=False)
    language_concept_id: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_id: Mapped[int | None] = mapped_column(Integer)
    visit_occurrence_id: Mapped[int | None] = mapped_column(Integer)
    visit_detail_id: Mapped[int | None] = mapped_column(Integer)
    note_source_value: Mapped[str | None] = mapped_column(String(50))
    note_event_id: Mapped[int | None] = mapped_column(Integer)
    note_event_field_concept_id: Mapped[int | None] = mapped_column(Integer)


class OmopNoteNlpRow(Base):
    __tablename__ = "note_nlp"
    __table_args__ = {"schema": "omop"}

    note_nlp_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    note_id: Mapped[int] = mapped_column(ForeignKey("omop.note.note_id"), nullable=False)
    section_concept_id: Mapped[int | None] = mapped_column(Integer)
    snippet: Mapped[str | None] = mapped_column(String(250))
    offset: Mapped[str | None] = mapped_column("offset", String(50))
    lexical_variant: Mapped[str] = mapped_column(String(250), nullable=False)
    note_nlp_concept_id: Mapped[int | None] = mapped_column(Integer)
    note_nlp_source_concept_id: Mapped[int | None] = mapped_column(Integer)
    nlp_system: Mapped[str | None] = mapped_column(String(250))
    nlp_date: Mapped[date] = mapped_column(Date, nullable=False)
    nlp_datetime: Mapped[datetime | None] = mapped_column(DateTime)
    term_exists: Mapped[str | None] = mapped_column(String(1))
    term_temporal: Mapped[str | None] = mapped_column(String(50))
    term_modifiers: Mapped[str | None] = mapped_column(String(2000))


class ReleaseMembershipRow(Base):
    __tablename__ = "release_membership"
    __table_args__ = (
        UniqueConstraint(
            "research_release_id", "omop_table", "omop_fact_id", name="uq_release_fact"
        ),
        {"schema": "control"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    research_release_id: Mapped[str] = mapped_column(
        ForeignKey("control.research_release.release_id"), nullable=False
    )
    clinical_event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    omop_table: Mapped[str] = mapped_column(String(50), nullable=False)
    omop_fact_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
