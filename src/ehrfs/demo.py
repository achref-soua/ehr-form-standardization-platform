"""Deterministic synthetic state for the guided demonstration."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ehrfs.domain.enums import AnswerState, OmopDomain, RunStatus
from ehrfs.domain.identity import canonical_json_bytes, content_hash, deterministic_uuid
from ehrfs.domain.models import DisplayCondition, FormDefinition, ItemDefinition, ValueOption
from ehrfs.fingerprinting.service import fingerprint_form
from ehrfs.mapping.models import (
    MappingEntry,
    MappingReleaseArtifact,
    MappingScope,
    MappingTarget,
    MappingTestVector,
    VocabularyRelease,
)
from ehrfs.mapping.releases import sign_mapping_release
from ehrfs.omop.releases import ResearchReleaseManifest
from ehrfs.security.signing import ReleaseSigner
from ehrfs.storage.objects import ObjectStore, StoredObject
from ehrfs.storage.tables import (
    AuditEventRow,
    CatalogConceptRow,
    CoverageMetricRow,
    EstablishmentRow,
    FormVersionRow,
    LineageGraphRow,
    MappingDraftRow,
    MappingReleaseRow,
    OmopConceptRow,
    OmopObservationRow,
    OmopPersonRow,
    PipelineJobRow,
    QuarantineRow,
    ReleaseMembershipRow,
    ResearchReleaseRow,
    SourceSystemRow,
)

DEMO_NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
DEMO_MAPPING_V3 = "mapping_2026_08_v3"


def demo_vocabulary_release() -> VocabularyRelease:
    payload = {
        "vocabulary_id": "EHRFS_DEMO",
        "version": "2026-08",
        "concepts": ["DEMO-NKDA"],
    }
    return VocabularyRelease(
        release_id="vocab_demo_2026_08",
        vocabulary_version="EHRFS_DEMO 2026-08",
        source="project-owned non-clinical fixture",
        checksum_sha256=content_hash(payload),
    )


def allergy_mapping_entry(version: str) -> MappingEntry:
    form = allergy_form(version)
    fingerprints = fingerprint_form(form)
    vector_state = AnswerState.UNKNOWN if version == "4" else AnswerState.EXPLICITLY_ABSENT
    return MappingEntry(
        mapping_id=f"map-allergy-q1-v{version}",
        scope=MappingScope(
            ehr_product=form.ehr_product,
            form_family=form.form_family,
            item_path="Q1",
            source_fingerprint=fingerprints.source,
            compatibility_fingerprint=fingerprints.compatibility,
        ),
        declared_source_type="coding",
        target=MappingTarget(
            domain=OmopDomain.OBSERVATION,
            concept_id=2_000_001,
            concept_code="DEMO-NKDA",
            concept_name="No known drug allergy (demo concept)",
            vocabulary_id="EHRFS_DEMO",
            standard_concept=True,
        ),
        value_map={"Oui": "known-allergy"},
        missing_value_codes=("Inconnu",) if version == "4" else (),
        negative_value_codes=("Non",),
        tests=(
            MappingTestVector(
                name=f"v{version} missing or negative state remains explicit",
                source_state=vector_state,
                expected_state=vector_state,
            ),
        ),
    )


def demo_mapping_artifact(
    signer: ReleaseSigner,
    *,
    version: str = "3",
    release_id: str = DEMO_MAPPING_V3,
    parent_release_id: str | None = None,
    approved_at: datetime = DEMO_NOW,
) -> MappingReleaseArtifact:
    provisional = MappingReleaseArtifact(
        release_id=release_id,
        parent_release_id=parent_release_id,
        vocabulary_release=demo_vocabulary_release(),
        entries=(allergy_mapping_entry(version),),
        authored_by="engineer@demo.local",
        approved_by="steward@demo.local",
        approved_at=approved_at,
        payload_checksum_sha256="0" * 64,
        signature_base64="pending",
        signing_key_id=signer.key_id,
    )
    return sign_mapping_release(provisional, signer)


def demo_response_payload(version: str = "3") -> bytes:
    value = "Inconnu" if version == "4" else "Non"
    payload = {
        "resourceType": "QuestionnaireResponse",
        "id": f"allergy-response-v{version}",
        "authored": "2026-08-12T09:30:00Z",
        "item": [{"linkId": "Q1", "answer": [{"valueCoding": {"code": value}}]}],
    }
    return canonical_json_bytes(payload)


def ensure_demo_artifacts(
    session: Session,
    object_store: ObjectStore,
    signer: ReleaseSigner,
    *,
    raw_bucket: str,
    mapping_bucket: str,
    research_bucket: str,
) -> None:
    """Materialize every seeded release/evidence object and repair its database pointer."""
    mapping = demo_mapping_artifact(signer)
    mapping_bytes = canonical_json_bytes(mapping.model_dump(mode="json"))
    stored_mapping = object_store.put_immutable(
        bucket=mapping_bucket,
        namespace="mapping-releases",
        content=mapping_bytes,
        media_type="application/json",
    )
    mapping_row = session.get(MappingReleaseRow, DEMO_MAPPING_V3)
    if mapping_row is not None:
        mapping_row.artifact_object_key = stored_mapping.key
        mapping_row.checksum_sha256 = stored_mapping.checksum_sha256
        mapping_row.signature_base64 = mapping.signature_base64
        mapping_row.signing_key_id = mapping.signing_key_id

    source_objects: list[StoredObject] = []
    for version in ("3", "4"):
        definition = canonical_json_bytes(allergy_form(version).model_dump(mode="json"))
        response = demo_response_payload(version)
        source_objects.extend(
            (
                object_store.put_immutable(
                    bucket=raw_bucket,
                    namespace=f"demo/forms/v{version}",
                    content=definition,
                    media_type="application/json",
                ),
                object_store.put_immutable(
                    bucket=raw_bucket,
                    namespace=f"demo/responses/v{version}",
                    content=response,
                    media_type="application/fhir+json",
                ),
            )
        )
    v4_response = source_objects[-1]
    quarantine = session.scalar(
        select(QuarantineRow).where(QuarantineRow.reason == "UNKNOWN_FORM_VERSION")
    )
    if quarantine is not None:
        quarantine.evidence_json = {
            "bucket": raw_bucket,
            "object_key": v4_response.key,
            "checksum": v4_response.checksum_sha256,
        }

    release = session.get(ResearchReleaseRow, "release_2026_08")
    if release is not None:
        output_checksum = content_hash(
            {
                "published_count": release.published_count,
                "quarantined_count": release.quarantined_count,
                "seed": "2026-08",
            }
        )
        manifest = ResearchReleaseManifest(
            release_id=release.release_id,
            source_manifest_checksums=tuple(item.checksum_sha256 for item in source_objects),
            connector_version="demo-connectors/1.0.0",
            canonical_schema_version="1.0.0",
            mapping_release_id=DEMO_MAPPING_V3,
            rule_release_id="quality-rules/1.0.0",
            vocabulary_release_id=demo_vocabulary_release().release_id,
            container_image="ehrfs-worker:0.1.0",
            created_at=DEMO_NOW,
            output_checksum_sha256=output_checksum,
        )
        release_bytes = canonical_json_bytes(manifest.model_dump(mode="json"))
        stored_release = object_store.put_immutable(
            bucket=research_bucket,
            namespace="research-releases",
            content=release_bytes,
            media_type="application/json",
        )
        release.artifact_object_key = stored_release.key
        release.checksum_sha256 = stored_release.checksum_sha256


def allergy_form(version: str = "3") -> FormDefinition:
    options: tuple[ValueOption, ...] = (
        ValueOption(code="Oui", display="Oui"),
        ValueOption(code="Non", display="Non"),
    )
    if version == "4":
        options += (ValueOption(code="Inconnu", display="Inconnu"),)
    return FormDefinition(
        ehr_product="DemoEHR",
        ehr_version="2026.1",
        form_id="ATCD_ALLERGIES",
        form_family="allergy-history",
        version=version,
        title="Antécédents allergiques",
        items=(
            ItemDefinition(
                item_id="Q1",
                path="Q1",
                label="Allergie médicamenteuse connue ?",
                data_type="coding",
                order=0,
                required=True,
                value_options=options,
            ),
            ItemDefinition(
                item_id="Q2",
                path="Q2",
                label="Substance allergène",
                data_type="string",
                order=1,
                display_conditions=(
                    DisplayCondition(source_item_path="Q1", operator="eq", expected="Oui"),
                ),
            ),
        ),
        metadata={"synthetic": "true", "source": "project-owned fixture"},
    )


def blood_pressure_form() -> FormDefinition:
    return FormDefinition(
        ehr_product="DemoEHR",
        ehr_version="2026.1",
        form_id="VITALS_BP",
        form_family="vital-signs",
        version="2",
        title="Pression artérielle répétée",
        items=(
            ItemDefinition(
                item_id="BP",
                path="BP",
                label="Mesures",
                data_type="group",
                order=0,
                repeats=True,
                children=(
                    ItemDefinition(
                        item_id="SYS",
                        path="BP/SYS",
                        label="Systolique",
                        data_type="decimal",
                        order=0,
                        unit="mm[Hg]",
                    ),
                    ItemDefinition(
                        item_id="DIA",
                        path="BP/DIA",
                        label="Diastolique",
                        data_type="decimal",
                        order=1,
                        unit="mm[Hg]",
                    ),
                    ItemDefinition(
                        item_id="POSITION",
                        path="BP/POSITION",
                        label="Position",
                        data_type="coding",
                        order=2,
                    ),
                ),
            ),
        ),
        metadata={"synthetic": "true"},
    )


def _form_payload(form: FormDefinition) -> dict[str, Any]:
    fingerprints = fingerprint_form(form)
    return {
        "definition": form.model_dump(mode="json"),
        "source_fingerprint": fingerprints.source,
        "compatibility_fingerprint": fingerprints.compatibility,
    }


def reset_demo(session: Session) -> None:
    for table in (
        ReleaseMembershipRow,
        CoverageMetricRow,
        QuarantineRow,
        LineageGraphRow,
        MappingDraftRow,
        FormVersionRow,
        SourceSystemRow,
        ResearchReleaseRow,
        MappingReleaseRow,
        CatalogConceptRow,
        PipelineJobRow,
        OmopObservationRow,
        OmopPersonRow,
        OmopConceptRow,
        EstablishmentRow,
    ):
        session.execute(delete(table))


def seed_demo(session: Session, *, reset: bool = False) -> None:
    if reset:
        reset_demo(session)
    if session.scalar(select(EstablishmentRow.id).limit(1)) is not None:
        return

    sites = (
        EstablishmentRow(id="site-a", name="Site A — Hôpital Nord", region="Hauts-de-France"),
        EstablishmentRow(id="site-b", name="Site B — Centre Atlantique", region="Pays de la Loire"),
        EstablishmentRow(id="site-c", name="Site C — Clinique Est", region="Grand Est"),
        EstablishmentRow(id="site-d", name="Site D — CH Métropole", region="Île-de-France"),
    )
    session.add_all(sites)
    session.flush()
    for site in sites:
        session.add(
            SourceSystemRow(
                establishment_id=site.id,
                source_key=f"{site.id}-ehr",
                family="FHIR R4" if site.id == "site-a" else "EAV / CDA",
                version="2026.1",
            )
        )

    v3 = allergy_form("3")
    v4 = allergy_form("4")
    bp = blood_pressure_form()
    form_rows: list[FormVersionRow] = []
    for form, status in ((v3, "RELEASED"), (v4, "REVIEW_REQUIRED"), (bp, "RELEASED")):
        payload = _form_payload(form)
        row = FormVersionRow(
            establishment_id="site-a",
            form_id=form.form_id,
            family=form.form_family,
            version=form.version,
            title=form.title,
            source_fingerprint=payload["source_fingerprint"],
            compatibility_fingerprint=payload["compatibility_fingerprint"],
            definition_json=payload["definition"],
            mapping_status=status,
            created_at=DEMO_NOW,
        )
        form_rows.append(row)
        session.add(row)
    session.flush()

    release_payload = {
        "release_id": DEMO_MAPPING_V3,
        "form": "ATCD_ALLERGIES",
        "version": "3",
        "target": "EHRFS_DEMO:DEMO-NKDA",
        "tests": ["Non remains explicitly absent", "Q2 hidden remains not displayed"],
    }
    session.add(
        MappingReleaseRow(
            release_id=DEMO_MAPPING_V3,
            artifact_object_key="mapping-releases/mapping_2026_08_v3.json",
            checksum_sha256=content_hash(release_payload),
            signature_base64="seeded-demo-signature",
            signing_key_id="demo-key",
            authored_by="engineer@demo.local",
            approved_by="steward@demo.local",
            approved_at=DEMO_NOW,
        )
    )
    v4_row = next(row for row in form_rows if row.version == "4")
    session.add(
        MappingDraftRow(
            form_version_id=v4_row.id,
            status="IN_REVIEW",
            authored_by="engineer@demo.local",
            payload_json={
                "changed_items": ["Q1"],
                "change": "Value set adds Inconnu",
                "candidate": "Reuse v3 mapping and map Inconnu to UNKNOWN",
                "tests": ["Inconnu remains UNKNOWN"],
                "entry": allergy_mapping_entry("4").model_dump(mode="json"),
                "vocabulary_release": demo_vocabulary_release().model_dump(mode="json"),
            },
            updated_at=DEMO_NOW,
        )
    )

    succeeded_job = PipelineJobRow(
        job_type="pipeline.run",
        status=RunStatus.SUCCEEDED,
        idempotency_key="demo-v3-run",
        payload_json={"form_version": "3", "batch_id": "batch-2026-08-a"},
        correlation_id="demo-correlation-v3",
        attempts=1,
        maximum_attempts=3,
        available_at=DEMO_NOW,
        created_at=DEMO_NOW,
        started_at=DEMO_NOW,
        finished_at=DEMO_NOW,
    )
    quarantined_job = PipelineJobRow(
        job_type="pipeline.run",
        status=RunStatus.FAILED,
        idempotency_key="demo-v4-run",
        payload_json={"form_version": "4", "batch_id": "batch-2026-08-v4"},
        correlation_id="demo-correlation-v4",
        attempts=1,
        maximum_attempts=3,
        available_at=DEMO_NOW,
        created_at=DEMO_NOW,
        started_at=DEMO_NOW,
        finished_at=DEMO_NOW,
        last_error="UNKNOWN_FORM_VERSION: no released mapping binds the v4 fingerprint",
    )
    session.add_all((succeeded_job, quarantined_job))
    session.flush()

    session.add(
        QuarantineRow(
            job_id=quarantined_job.id,
            establishment_id="site-a",
            form_id="ATCD_ALLERGIES",
            item_path="Q1",
            reason="UNKNOWN_FORM_VERSION",
            status="OPEN",
            evidence_json={
                "object_key": "raw/site-a/batch-2026-08-v4/response-1001.json",
                "checksum": "8f3c" + "0" * 60,
            },
            context_json={
                "version": "4",
                "changed_value": "Inconnu",
                "resolution": "Approve and release the reviewed v4 mapping, then replay",
            },
            created_at=DEMO_NOW,
        )
    )
    session.add(
        ResearchReleaseRow(
            release_id="release_2026_08",
            mapping_release_id=DEMO_MAPPING_V3,
            artifact_object_key="research-releases/release_2026_08.json",
            checksum_sha256="d" * 64,
            published_count=842,
            quarantined_count=37,
            created_at=DEMO_NOW,
        )
    )
    session.add(
        CatalogConceptRow(
            concept_key="allergy-history",
            display_name="Allergy history",
            definition="Known or explicitly absent allergy history from controlled sources.",
            vocabulary_id="EHRFS_DEMO",
            concept_code="DEMO-NKDA",
            limitations="Synthetic demonstration; Site B eligibility denominator is unavailable.",
            updated_at=DEMO_NOW,
        )
    )
    session.flush()
    coverage_rows: tuple[tuple[str, int | None, int, int, int, str, str], ...] = (
        ("site-a", 1000, 870, 840, 210, "Structured form", "VALIDATED"),
        ("site-b", None, 431, 392, 88, "CDA rules", "LIMITED"),
        ("site-c", 700, 0, 0, 0, "No mapped source", "ABSENT"),
        ("site-d", 800, 496, 440, 97, "Structured + OCR", "MONITORED"),
    )
    for site_id, eligible, recorded, usable, positive, method, status in coverage_rows:
        completion = (
            None if eligible is None or eligible == 0 else Decimal(recorded) / Decimal(eligible)
        )
        usable_coverage = (
            None if eligible is None or eligible == 0 else Decimal(usable) / Decimal(eligible)
        )
        prevalence = None if usable == 0 else Decimal(positive) / Decimal(usable)
        session.add(
            CoverageMetricRow(
                concept_key="allergy-history",
                establishment_id=site_id,
                research_release_id="release_2026_08",
                period_start=date(2026, 1, 1),
                period_end=date(2026, 8, 31),
                eligible_count=eligible,
                recorded_count=recorded,
                usable_count=usable,
                positive_count=positive,
                completion=completion,
                usable_coverage=usable_coverage,
                prevalence=prevalence,
                method=method,
                quality_status=status,
            )
        )

    session.add(
        OmopConceptRow(
            concept_id=2_000_001,
            concept_name="No known drug allergy (demo concept)",
            domain_id="Observation",
            vocabulary_id="EHRFS_DEMO",
            concept_class_id="Demo",
            standard_concept="S",
            concept_code="DEMO-NKDA",
            valid_start_date=date(2026, 1, 1),
            valid_end_date=date(2099, 12, 31),
        )
    )
    session.add(
        OmopPersonRow(
            person_id=1,
            gender_concept_id=0,
            year_of_birth=1984,
            race_concept_id=0,
            ethnicity_concept_id=0,
            person_source_value="p_83f2b9a4d1c3",
        )
    )
    # SQLAlchemy has no ORM relationship between these OMOP rows, so make
    # the foreign-key ordering explicit instead of relying on unit-of-work sort.
    session.flush()
    session.add(
        OmopObservationRow(
            observation_id=1,
            person_id=1,
            observation_concept_id=2_000_001,
            observation_date=date(2026, 8, 12),
            observation_datetime=datetime(2026, 8, 12, 9, 30, tzinfo=UTC),
            observation_type_concept_id=0,
            value_as_string="EXPLICITLY_ABSENT",
            observation_source_value="Q1=Non",
        )
    )
    session.add(
        ReleaseMembershipRow(
            research_release_id="release_2026_08",
            clinical_event_id=deterministic_uuid(
                "canonical-answer", "site-a", "response-991", "Q1"
            ),
            omop_table="observation",
            omop_fact_id=1,
        )
    )

    lineage = {
        "nodes": [
            {"id": "raw:response-991", "kind": "raw", "label": "response_991.json"},
            {"id": "canonical:q1", "kind": "canonical", "label": "Q1 explicitly absent"},
            {"id": "mapping:v3", "kind": "mapping", "label": "mapping_2026_08_v3"},
            {"id": "quality:q1", "kind": "quality", "label": "All gates pass"},
            {"id": "omop:observation:1", "kind": "omop", "label": "Observation 1"},
            {"id": "catalog:allergy", "kind": "catalog", "label": "Allergy history"},
        ],
        "edges": [
            {
                "source": "raw:response-991",
                "target": "canonical:q1",
                "relation": "canonicalized_as",
            },
            {"source": "canonical:q1", "target": "mapping:v3", "relation": "standardized_by"},
            {"source": "mapping:v3", "target": "quality:q1", "relation": "validated_by"},
            {"source": "quality:q1", "target": "omop:observation:1", "relation": "published_as"},
            {
                "source": "omop:observation:1",
                "target": "catalog:allergy",
                "relation": "summarized_by",
            },
        ],
    }
    session.add(
        LineageGraphRow(root_node_id="omop:observation:1", graph_json=lineage, created_at=DEMO_NOW)
    )
    session.add(
        AuditEventRow(
            occurred_at=DEMO_NOW,
            actor_id="steward@demo.local",
            action="mapping.release.approved",
            resource_type="mapping_release",
            resource_id="mapping_2026_08_v3",
            correlation_id="demo-release-v3",
            metadata_json={"synthetic": True},
        )
    )
