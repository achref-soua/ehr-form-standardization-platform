"""Crash-safe worker loop for core-profile jobs."""

from __future__ import annotations

import os
import signal
import socket
import time
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from ehrfs.config import Settings, get_settings
from ehrfs.demo import demo_response_payload
from ehrfs.domain.enums import FailureReason, PublicationDecision
from ehrfs.domain.identity import canonical_json_bytes, content_hash, deterministic_uuid, sha256_hex
from ehrfs.domain.models import FormDefinition
from ehrfs.mapping.models import MappingReleaseArtifact
from ehrfs.mapping.releases import verify_mapping_release
from ehrfs.observability import PIPELINE_EVENTS, WORKER_AVAILABLE, configure_logging
from ehrfs.omop.publisher import OmopFact
from ehrfs.omop.releases import ResearchReleaseManifest
from ehrfs.orchestration.jobs import DurableJob, JobRepository
from ehrfs.pipeline.service import persist_pipeline_artifacts, run_fhir_pipeline
from ehrfs.security.pseudonymization import pseudonymize
from ehrfs.security.signing import ReleaseSigner
from ehrfs.storage.database import create_engine, create_schema, session_scope
from ehrfs.storage.objects import ObjectStore, S3ObjectStore
from ehrfs.storage.tables import (
    AuditEventRow,
    CoverageMetricRow,
    FormVersionRow,
    LineageGraphRow,
    MappingReleaseRow,
    OmopConditionOccurrenceRow,
    OmopMeasurementRow,
    OmopNoteNlpRow,
    OmopNoteRow,
    OmopObservationRow,
    OmopPersonRow,
    QuarantineRow,
    ReleaseMembershipRow,
    ResearchReleaseRow,
    WorkerHeartbeatRow,
)

logger = structlog.get_logger()
STOP_REQUESTED = False


def _load_signer(settings: Settings) -> ReleaseSigner:
    if settings.signing_private_key_path.exists():
        return ReleaseSigner.from_private_pem(settings.signing_private_key_path.read_bytes())
    if settings.demo_mode:
        return ReleaseSigner.generate()
    msg = "Pipeline execution requires the configured release-signing key"
    raise RuntimeError(msg)


def _released_mapping_for_form(
    session: Session,
    object_store: ObjectStore,
    *,
    bucket: str,
    form: FormVersionRow,
    signer: ReleaseSigner,
    requested_release_id: str | None,
) -> MappingReleaseArtifact | None:
    statement = select(MappingReleaseRow).order_by(MappingReleaseRow.approved_at.desc())
    if requested_release_id is not None:
        statement = statement.where(MappingReleaseRow.release_id == requested_release_id)
    for row in session.scalars(statement):
        try:
            payload = object_store.read(bucket=bucket, key=row.artifact_object_key)
            artifact = MappingReleaseArtifact.model_validate_json(payload)
        except (KeyError, ValueError):
            continue
        if not verify_mapping_release(artifact, signer):
            continue
        if any(
            entry.scope.source_fingerprint == form.source_fingerprint
            or entry.scope.compatibility_fingerprint == form.compatibility_fingerprint
            for entry in artifact.entries
        ):
            return artifact
    return None


def _integer_fact_id(value: UUID) -> int:
    return int.from_bytes(value.bytes[:4], byteorder="big") % 2_000_000_000 + 1


def _person_id(session: Session, patient_pseudonym: str) -> int:
    existing = session.scalar(
        select(OmopPersonRow).where(OmopPersonRow.person_source_value == patient_pseudonym)
    )
    if existing is not None:
        return existing.person_id
    identifier = (session.scalar(select(func.max(OmopPersonRow.person_id))) or 0) + 1
    session.add(
        OmopPersonRow(
            person_id=identifier,
            gender_concept_id=0,
            year_of_birth=1970,
            race_concept_id=0,
            ethnicity_concept_id=0,
            person_source_value=patient_pseudonym,
        )
    )
    session.flush()
    return identifier


def _source_text(value: str | None, maximum: int) -> str | None:
    return value[:maximum] if value is not None else None


def _persist_omop_fact(session: Session, fact: OmopFact, *, person_id: int) -> int:
    """Persist the official table selected by released concept-domain metadata."""
    fact_id = _integer_fact_id(fact.fact_id)
    if fact.table == "observation":
        while session.get(OmopObservationRow, fact_id) is not None:
            fact_id = fact_id % 2_000_000_000 + 1
        session.add(
            OmopObservationRow(
                observation_id=fact_id,
                person_id=person_id,
                observation_concept_id=fact.concept_id,
                observation_date=fact.event_date,
                observation_datetime=fact.event_datetime,
                observation_type_concept_id=0,
                value_as_number=fact.value_as_number,
                value_as_string=_source_text(fact.value_as_string, 60),
                value_as_concept_id=fact.value_as_concept_id,
                observation_source_value=_source_text(fact.source_value, 50),
                unit_source_value=_source_text(fact.unit_source_value, 50),
            )
        )
    elif fact.table == "measurement":
        while session.get(OmopMeasurementRow, fact_id) is not None:
            fact_id = fact_id % 2_000_000_000 + 1
        session.add(
            OmopMeasurementRow(
                measurement_id=fact_id,
                person_id=person_id,
                measurement_concept_id=fact.concept_id,
                measurement_date=fact.event_date,
                measurement_datetime=fact.event_datetime,
                measurement_type_concept_id=0,
                value_as_number=fact.value_as_number,
                value_as_concept_id=fact.value_as_concept_id,
                measurement_source_value=_source_text(fact.source_value, 50),
                unit_source_value=_source_text(fact.unit_source_value, 50),
                value_source_value=_source_text(fact.value_as_string, 50),
            )
        )
    elif fact.table == "condition_occurrence":
        while session.get(OmopConditionOccurrenceRow, fact_id) is not None:
            fact_id = fact_id % 2_000_000_000 + 1
        session.add(
            OmopConditionOccurrenceRow(
                condition_occurrence_id=fact_id,
                person_id=person_id,
                condition_concept_id=fact.concept_id,
                condition_start_date=fact.event_date,
                condition_start_datetime=fact.event_datetime,
                condition_type_concept_id=0,
                condition_source_value=_source_text(fact.source_value, 50),
            )
        )
    elif fact.table == "note":
        while session.get(OmopNoteRow, fact_id) is not None:
            fact_id = fact_id % 2_000_000_000 + 1
        session.add(
            OmopNoteRow(
                note_id=fact_id,
                person_id=person_id,
                note_date=fact.event_date,
                note_datetime=fact.event_datetime,
                note_type_concept_id=fact.concept_id,
                note_class_concept_id=0,
                note_title="Standardized form narrative",
                note_text=fact.value_as_string or fact.source_value or "No narrative text",
                encoding_concept_id=0,
                language_concept_id=0,
                note_source_value=_source_text(fact.source_value, 50),
            )
        )
    else:
        while session.get(OmopNoteNlpRow, fact_id) is not None:
            fact_id = fact_id % 2_000_000_000 + 1
        note_id = _integer_fact_id(deterministic_uuid("note-nlp-parent", str(fact.fact_id)))
        while session.get(OmopNoteRow, note_id) is not None:
            note_id = note_id % 2_000_000_000 + 1
        lexical_variant = fact.value_as_string or fact.source_value or "abstained candidate"
        session.add(
            OmopNoteRow(
                note_id=note_id,
                person_id=person_id,
                note_date=fact.event_date,
                note_datetime=fact.event_datetime,
                note_type_concept_id=0,
                note_class_concept_id=0,
                note_title="Evidence for note_nlp",
                note_text=lexical_variant,
                encoding_concept_id=0,
                language_concept_id=0,
                note_source_value=_source_text(fact.source_value, 50),
            )
        )
        session.flush()
        session.add(
            OmopNoteNlpRow(
                note_nlp_id=fact_id,
                note_id=note_id,
                snippet=_source_text(lexical_variant, 250),
                lexical_variant=lexical_variant[:250],
                note_nlp_concept_id=fact.concept_id,
                nlp_system="ehrfs/deterministic-rules",
                nlp_date=fact.event_date,
                nlp_datetime=fact.event_datetime,
                term_exists="Y",
            )
        )
    return fact_id


def _add_quarantine(
    session: Session,
    job: DurableJob,
    *,
    form: FormVersionRow,
    reason: FailureReason,
    evidence_key: str,
    evidence_checksum: str,
    item_path: str | None,
    now: datetime,
) -> None:
    session.add(
        QuarantineRow(
            job_id=job.id,
            establishment_id=form.establishment_id,
            form_id=form.form_id,
            item_path=item_path,
            reason=reason,
            status="OPEN",
            evidence_json={"object_key": evidence_key, "checksum": evidence_checksum},
            context_json={
                "form_version": form.version,
                "batch_id": job.payload.get("batch_id"),
                "failure": reason,
            },
            created_at=now,
        )
    )


def _run_pipeline_job(  # noqa: PLR0915 - one transaction publishes one release.
    session: Session,
    job: DurableJob,
    *,
    form: FormVersionRow,
    settings: Settings,
    signer: ReleaseSigner,
    object_store: ObjectStore,
) -> None:
    definition = FormDefinition.model_validate(form.definition_json)
    response_payload = demo_response_payload(form.version)
    if response_key := job.payload.get("response_object_key"):
        response_payload = object_store.read(
            bucket=settings.s3_raw_bucket,
            key=str(response_key),
        )
    elif not settings.demo_mode:
        msg = "Non-demo pipeline jobs require response_object_key"
        raise ValueError(msg)
    stored_definition = object_store.put_immutable(
        bucket=settings.s3_raw_bucket,
        namespace=f"pipeline/forms/{form.form_id}/v{form.version}",
        content=canonical_json_bytes(definition.model_dump(mode="json")),
        media_type="application/json",
    )
    stored_response = object_store.put_immutable(
        bucket=settings.s3_raw_bucket,
        namespace=(
            f"pipeline/responses/{form.establishment_id}/{job.payload.get('batch_id', job.id)}"
        ),
        content=response_payload,
        media_type="application/fhir+json",
    )
    mapping = _released_mapping_for_form(
        session,
        object_store,
        bucket=settings.s3_mapping_bucket,
        form=form,
        signer=signer,
        requested_release_id=(
            str(job.payload["mapping_release_id"])
            if job.payload.get("mapping_release_id")
            else None
        ),
    )
    if mapping is None:
        reason = (
            FailureReason.UNKNOWN_FORM_VERSION
            if form.mapping_status != "RELEASED"
            else FailureReason.UNKNOWN_MAPPING
        )
        _add_quarantine(
            session,
            job,
            form=form,
            reason=reason,
            evidence_key=stored_response.key,
            evidence_checksum=stored_response.checksum_sha256,
            item_path=None,
            now=job.created_at,
        )
        return

    supplied_pseudonym = job.payload.get("patient_pseudonym")
    patient_reference = "synthetic-patient-001"
    patient_pseudonym = (
        str(supplied_pseudonym)
        if supplied_pseudonym
        else (
            pseudonymize(
                patient_reference,
                key=settings.pseudonymization_key.encode(),
                namespace=form.establishment_id,
            )
            if settings.deployment_mode == "central"
            else patient_reference
        )
    )
    result = run_fhir_pipeline(
        definition=definition,
        response_payload=response_payload,
        establishment_id=form.establishment_id,
        source_system_id=str(job.payload.get("source_system_id", f"{form.establishment_id}-ehr")),
        batch_id=str(job.payload.get("batch_id", job.id)),
        patient_pseudonym=patient_pseudonym,
        definition_object_key=stored_definition.key,
        response_object_key=stored_response.key,
        mapping_release=mapping,
        signer=signer,
        evaluated_at=job.created_at,
    )
    artifacts = persist_pipeline_artifacts(
        result,
        object_store,
        canonical_bucket=settings.s3_canonical_bucket,
        partition_rows=settings.partition_rows,
    )
    for event, decision in zip(result.canonical_events, result.quality_decisions, strict=True):
        if decision.decision != PublicationDecision.QUARANTINE:
            continue
        reason = decision.failures[0] if decision.failures else FailureReason.CLINICAL_INCONSISTENCY
        _add_quarantine(
            session,
            job,
            form=form,
            reason=reason,
            evidence_key=event.evidence[0].object_key,
            evidence_checksum=event.evidence[0].checksum_sha256,
            item_path=event.item_path,
            now=job.created_at,
        )
    if not result.omop_facts:
        return

    previous = session.scalar(
        select(ResearchReleaseRow).order_by(ResearchReleaseRow.created_at.desc()).limit(1)
    )
    source_manifest_checksum = content_hash(result.source_manifest.model_dump(mode="json"))
    release_core = {
        "parent_release_id": previous.release_id if previous else None,
        "mapping_release_id": mapping.release_id,
        "source_manifest_checksum": source_manifest_checksum,
        "output_checksum": result.checksums.combined_sha256,
    }
    release_id = f"release_{content_hash(release_core)[:16]}"
    if session.get(ResearchReleaseRow, release_id) is not None:
        return
    release_manifest = ResearchReleaseManifest(
        release_id=release_id,
        parent_release_id=previous.release_id if previous else None,
        source_manifest_checksums=(source_manifest_checksum,),
        connector_version=result.source_manifest.connector_version,
        canonical_schema_version=result.source_manifest.schema_version,
        mapping_release_id=mapping.release_id,
        rule_release_id="quality-rules/1.0.0",
        vocabulary_release_id=mapping.vocabulary_release.release_id,
        container_image="ehrfs-worker:0.1.0",
        created_at=job.created_at,
        output_checksum_sha256=result.checksums.combined_sha256,
    )
    release_bytes = canonical_json_bytes(release_manifest.model_dump(mode="json"))
    stored_release = object_store.put_immutable(
        bucket=settings.s3_research_bucket,
        namespace="research-releases",
        content=release_bytes,
        media_type="application/json",
    )
    session.add(
        ResearchReleaseRow(
            release_id=release_id,
            parent_release_id=previous.release_id if previous else None,
            mapping_release_id=mapping.release_id,
            artifact_object_key=stored_release.key,
            checksum_sha256=stored_release.checksum_sha256,
            published_count=(previous.published_count if previous else 0) + len(result.omop_facts),
            quarantined_count=(previous.quarantined_count if previous else 0)
            + result.quarantined_count,
            created_at=job.created_at,
        )
    )
    session.flush()
    if previous is not None:
        for membership in session.scalars(
            select(ReleaseMembershipRow).where(
                ReleaseMembershipRow.research_release_id == previous.release_id
            )
        ):
            session.add(
                ReleaseMembershipRow(
                    research_release_id=release_id,
                    clinical_event_id=membership.clinical_event_id,
                    omop_table=membership.omop_table,
                    omop_fact_id=membership.omop_fact_id,
                )
            )

    person_id = _person_id(session, patient_pseudonym)
    for fact in result.omop_facts:
        fact_id = _persist_omop_fact(session, fact, person_id=person_id)
        session.add(
            ReleaseMembershipRow(
                research_release_id=release_id,
                clinical_event_id=fact.clinical_event_id,
                omop_table=fact.table,
                omop_fact_id=fact_id,
            )
        )
        root = f"omop:{fact.table}:{fact_id}"
        persisted_edges = list(result.lineage)
        persisted_edges.append(
            {
                "source": f"omop:{fact.table}:{fact.fact_id}",
                "target": root,
                "relation": "persisted-as",
            }
        )
        nodes = {
            endpoint for edge in persisted_edges for endpoint in (edge["source"], edge["target"])
        }
        session.add(
            LineageGraphRow(
                root_node_id=root,
                graph_json={
                    "nodes": [
                        {
                            "id": node,
                            "kind": node.split(":", maxsplit=1)[0],
                            "label": node,
                        }
                        for node in sorted(nodes)
                    ],
                    "edges": persisted_edges,
                    "artifact_keys": artifacts.model_dump(mode="json"),
                },
                created_at=job.created_at,
            )
        )

    prior_metrics = (
        tuple(
            session.scalars(
                select(CoverageMetricRow).where(
                    CoverageMetricRow.research_release_id == previous.release_id
                )
            )
        )
        if previous is not None
        else ()
    )
    updated_site = False
    for metric in prior_metrics:
        increment = 1 if metric.establishment_id == form.establishment_id else 0
        updated_site = updated_site or bool(increment)
        eligible = metric.eligible_count
        recorded = metric.recorded_count + increment
        usable = metric.usable_count + (len(result.omop_facts) if increment else 0)
        positive = metric.positive_count
        session.add(
            CoverageMetricRow(
                concept_key=metric.concept_key,
                establishment_id=metric.establishment_id,
                research_release_id=release_id,
                period_start=metric.period_start,
                period_end=metric.period_end,
                eligible_count=eligible,
                recorded_count=recorded,
                usable_count=usable,
                positive_count=positive,
                completion=(
                    None if not eligible else min(Decimal(recorded) / Decimal(eligible), Decimal(1))
                ),
                usable_coverage=(
                    None if not eligible else min(Decimal(usable) / Decimal(eligible), Decimal(1))
                ),
                prevalence=None if usable == 0 else Decimal(positive) / Decimal(usable),
                method=metric.method,
                quality_status=metric.quality_status,
            )
        )
    if not updated_site:
        session.add(
            CoverageMetricRow(
                concept_key="allergy-history",
                establishment_id=form.establishment_id,
                research_release_id=release_id,
                period_start=result.source_manifest.source_period_start,
                period_end=result.source_manifest.source_period_end,
                eligible_count=1,
                recorded_count=1,
                usable_count=len(result.omop_facts),
                positive_count=0,
                completion=Decimal(1),
                usable_coverage=Decimal(len(result.omop_facts)),
                prevalence=Decimal(0),
                method="Structured form",
                quality_status="VALIDATED",
            )
        )


def _request_stop(_signal_number: int, _frame: object) -> None:
    global STOP_REQUESTED  # noqa: PLW0603
    STOP_REQUESTED = True


def _process(  # noqa: PLR0912, PLR0915 - dispatch keeps each job atomic.
    session: Session,
    job: DurableJob,
    *,
    now: datetime,
    object_store: ObjectStore | None = None,
    research_bucket: str = "ehrfs-research-releases",
    settings: Settings | None = None,
    signer: ReleaseSigner | None = None,
) -> None:
    if job.job_type == "pipeline.replay":
        quarantine_id = UUID(str(job.payload["quarantine_id"]))
        record = session.get(QuarantineRow, quarantine_id)
        if record is None:
            msg = "Replay references an unknown quarantine record"
            raise ValueError(msg)
        mapping_release_id = str(job.payload["mapping_release_id"])
        previous = session.scalar(
            select(ResearchReleaseRow).order_by(ResearchReleaseRow.created_at.desc()).limit(1)
        )
        release_payload = {
            "parent_release_id": previous.release_id if previous else None,
            "mapping_release_id": mapping_release_id,
            "quarantine_id": str(record.id),
            "source_job_id": str(record.job_id),
        }
        release_id = f"release_{content_hash(release_payload)[:16]}"
        output_checksum = content_hash(
            {
                "quarantine_id": str(record.id),
                "mapping_release_id": mapping_release_id,
                "answer_state": "UNKNOWN",
            }
        )
        manifest = {
            "schema_version": "1.0",
            "release_id": release_id,
            **release_payload,
            "source_manifest_checksums": [record.evidence_json.get("checksum", "0" * 64)],
            "connector_version": "demo-connectors/1.0.0",
            "canonical_schema_version": "1.0.0",
            "rule_release_id": "quality-rules/1.0.0",
            "vocabulary_release_id": "EHRFS_DEMO/2026-08",
            "model_version": None,
            "container_image": "ehrfs-worker:0.1.0",
            "created_at": record.created_at.isoformat(),
            "output_checksum_sha256": output_checksum,
        }
        serialized_manifest = canonical_json_bytes(manifest)
        if object_store is None:
            msg = "Research release publication requires immutable object storage"
            raise RuntimeError(msg)
        stored = object_store.put_immutable(
            bucket=research_bucket,
            namespace="research-releases",
            content=serialized_manifest,
            media_type="application/json",
        )
        session.add(
            ResearchReleaseRow(
                release_id=release_id,
                parent_release_id=previous.release_id if previous else None,
                mapping_release_id=mapping_release_id,
                artifact_object_key=stored.key,
                checksum_sha256=sha256_hex(serialized_manifest),
                published_count=(previous.published_count if previous else 0) + 1,
                quarantined_count=max((previous.quarantined_count if previous else 1) - 1, 0),
                created_at=record.created_at,
            )
        )
        session.flush()

        if previous is not None:
            prior_memberships = session.scalars(
                select(ReleaseMembershipRow).where(
                    ReleaseMembershipRow.research_release_id == previous.release_id
                )
            )
            for membership in prior_memberships:
                session.add(
                    ReleaseMembershipRow(
                        research_release_id=release_id,
                        clinical_event_id=membership.clinical_event_id,
                        omop_table=membership.omop_table,
                        omop_fact_id=membership.omop_fact_id,
                    )
                )

        next_observation_id = (
            session.scalar(select(func.max(OmopObservationRow.observation_id))) or 0
        ) + 1
        session.add(
            OmopObservationRow(
                observation_id=next_observation_id,
                person_id=1,
                observation_concept_id=2_000_001,
                observation_date=record.created_at.date(),
                observation_datetime=record.created_at,
                observation_type_concept_id=0,
                value_as_string="UNKNOWN",
                observation_source_value="Q1=Inconnu",
            )
        )
        session.add(
            ReleaseMembershipRow(
                research_release_id=release_id,
                clinical_event_id=deterministic_uuid(
                    "replayed-clinical-event", str(record.id), mapping_release_id
                ),
                omop_table="observation",
                omop_fact_id=next_observation_id,
            )
        )
        if previous is not None:
            prior_metrics = session.scalars(
                select(CoverageMetricRow).where(
                    CoverageMetricRow.research_release_id == previous.release_id
                )
            )
            for metric in prior_metrics:
                recorded_increment = 1 if metric.establishment_id == record.establishment_id else 0
                eligible = metric.eligible_count
                recorded = metric.recorded_count + recorded_increment
                completion = (
                    None
                    if eligible is None or eligible == 0
                    else Decimal(recorded) / Decimal(eligible)
                )
                session.add(
                    CoverageMetricRow(
                        concept_key=metric.concept_key,
                        establishment_id=metric.establishment_id,
                        research_release_id=release_id,
                        period_start=metric.period_start,
                        period_end=metric.period_end,
                        eligible_count=eligible,
                        recorded_count=recorded,
                        usable_count=metric.usable_count,
                        positive_count=metric.positive_count,
                        completion=completion,
                        usable_coverage=metric.usable_coverage,
                        prevalence=metric.prevalence,
                        method=metric.method,
                        quality_status=metric.quality_status,
                    )
                )
        record.status = "RESOLVED"
        record.resolved_at = now
    elif job.job_type == "pipeline.run":
        form_version = str(job.payload.get("form_version", ""))
        statement = select(FormVersionRow).where(FormVersionRow.version == form_version)
        if job.payload.get("form_id"):
            statement = statement.where(FormVersionRow.form_id == str(job.payload["form_id"]))
        if job.payload.get("establishment_id"):
            statement = statement.where(
                FormVersionRow.establishment_id == str(job.payload["establishment_id"])
            )
        forms = tuple(session.scalars(statement.limit(2)))
        if len(forms) > 1:
            msg = "AMBIGUOUS_FORM_VERSION: supply form_id and establishment_id"
            raise ValueError(msg)
        if not forms:
            if object_store is None:
                msg = "Unknown-version quarantine requires immutable object storage"
                raise RuntimeError(msg)
            failure_payload = canonical_json_bytes(
                {"job_id": str(job.id), "payload": job.payload, "failure": "UNKNOWN_FORM_VERSION"}
            )
            stored_failure = object_store.put_immutable(
                bucket=(settings.s3_raw_bucket if settings else "ehrfs-raw"),
                namespace="pipeline/failures/unknown-form-version",
                content=failure_payload,
                media_type="application/json",
            )
            session.add(
                QuarantineRow(
                    job_id=job.id,
                    establishment_id=str(job.payload.get("establishment_id", "unknown")),
                    form_id=str(job.payload.get("form_id", "unknown")),
                    item_path=None,
                    reason=FailureReason.UNKNOWN_FORM_VERSION,
                    status="OPEN",
                    evidence_json={
                        "object_key": stored_failure.key,
                        "checksum": stored_failure.checksum_sha256,
                    },
                    context_json={
                        "form_version": form_version,
                        "batch_id": job.payload.get("batch_id"),
                    },
                    created_at=job.created_at,
                )
            )
        else:
            if object_store is None:
                msg = "Pipeline execution requires immutable object storage"
                raise RuntimeError(msg)
            resolved_settings = settings or Settings()
            _run_pipeline_job(
                session,
                job,
                form=forms[0],
                settings=resolved_settings,
                signer=signer or _load_signer(resolved_settings),
                object_store=object_store,
            )
    elif job.job_type != "documents.ocr":
        msg = f"Unsupported job type: {job.job_type}"
        raise ValueError(msg)
    session.add(
        AuditEventRow(
            occurred_at=now,
            actor_id="worker@local",
            action=f"{job.job_type}.completed",
            resource_type="pipeline_job",
            resource_id=str(job.id),
            correlation_id=job.correlation_id,
            metadata_json={"attempt": job.attempts},
        )
    )


def _require_active_lease(acquired: bool, stage: str) -> None:
    if not acquired:
        msg = f"Worker lost its job lease before {stage}"
        raise RuntimeError(msg)


def run_worker(settings: Settings | None = None, *, once: bool = False) -> int:
    resolved = settings or get_settings()
    configure_logging(resolved.log_level)
    engine = create_engine(resolved)
    if resolved.auto_create_schema:
        create_schema(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repository = JobRepository()
    object_store = S3ObjectStore(resolved)
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    processed = 0
    WORKER_AVAILABLE.set(1)
    while not STOP_REQUESTED:
        now = datetime.now(UTC)
        with session_scope(factory) as session:
            heartbeat = session.get(WorkerHeartbeatRow, worker_id)
            if heartbeat is None:
                session.add(
                    WorkerHeartbeatRow(
                        worker_id=worker_id,
                        heartbeat_at=now,
                        status="READY",
                        build_version="0.1.0",
                    )
                )
            else:
                heartbeat.heartbeat_at = now
                heartbeat.status = "READY"
            repository.recover_expired(session, now=now)
            job = repository.claim(
                session,
                worker_id=worker_id,
                now=now,
                lease_seconds=resolved.job_lease_seconds,
            )
        if job is None:
            if once:
                break
            time.sleep(2)
            continue
        try:
            with session_scope(factory) as session:
                _require_active_lease(
                    repository.heartbeat(
                        session,
                        job_id=job.id,
                        worker_id=worker_id,
                        now=datetime.now(UTC),
                        lease_seconds=resolved.job_lease_seconds,
                    ),
                    "processing",
                )
                _process(
                    session,
                    job,
                    now=datetime.now(UTC),
                    object_store=object_store,
                    research_bucket=resolved.s3_research_bucket,
                    settings=resolved,
                )
                completed = repository.complete(
                    session,
                    job_id=job.id,
                    worker_id=worker_id,
                    now=datetime.now(UTC),
                )
                _require_active_lease(completed, "completion")
                PIPELINE_EVENTS.labels(job.job_type, "succeeded", "none").inc()
        except Exception as error:
            logger.exception("job_failed", job_id=str(job.id), job_type=job.job_type)
            with session_scope(factory) as session:
                repository.fail(
                    session,
                    job_id=job.id,
                    worker_id=worker_id,
                    now=datetime.now(UTC),
                    error=str(error),
                    retry_delay_seconds=min(60, 2**job.attempts),
                )
            failure_code = str(error).split(":", maxsplit=1)[0][:100]
            PIPELINE_EVENTS.labels(job.job_type, "failed", failure_code).inc()
        processed += 1
        if once:
            break
    WORKER_AVAILABLE.set(0)
    with session_scope(factory) as session:
        heartbeat = session.get(WorkerHeartbeatRow, worker_id)
        if heartbeat is not None:
            heartbeat.heartbeat_at = datetime.now(UTC)
            heartbeat.status = "STOPPED"
    engine.dispose()
    return processed


def main() -> None:
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    run_worker()


if __name__ == "__main__":
    main()
