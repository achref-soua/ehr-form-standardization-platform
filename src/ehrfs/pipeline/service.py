"""Pure bounded pipeline from a registered form response to research artifacts."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from ehrfs.domain.enums import PublicationDecision
from ehrfs.domain.errors import DomainError
from ehrfs.domain.identity import canonical_json_bytes, content_hash, deterministic_uuid, sha256_hex
from ehrfs.domain.models import CanonicalAnswerEvent, DomainModel, FormDefinition, SourceManifest
from ehrfs.ingestion.fhir import FhirR4Adapter
from ehrfs.mapping.models import MappingReleaseArtifact
from ehrfs.mapping.releases import verify_mapping_release
from ehrfs.omop.publisher import OmopFact, publish_event
from ehrfs.quality.engine import QualityDecision, QualityEngine
from ehrfs.security.signing import ReleaseSigner
from ehrfs.standardization.service import Standardizer
from ehrfs.storage.objects import ObjectStore
from ehrfs.storage.parquet import CanonicalParquetWriter


class PipelineChecksums(DomainModel):
    canonical_sha256: str
    quality_sha256: str
    omop_sha256: str
    lineage_sha256: str
    catalog_sha256: str
    combined_sha256: str


class PipelineResult(DomainModel):
    source_manifest: SourceManifest
    canonical_events: tuple[CanonicalAnswerEvent, ...]
    quality_decisions: tuple[QualityDecision, ...]
    omop_facts: tuple[OmopFact, ...]
    published_count: int
    quarantined_count: int
    omitted_count: int
    lineage: tuple[dict[str, str], ...]
    catalog_summary: dict[str, object]
    checksums: PipelineChecksums


class PipelineArtifactSet(DomainModel):
    source_manifest_key: str
    canonical_parquet_keys: tuple[str, ...]
    quality_key: str
    omop_key: str
    lineage_key: str
    catalog_key: str


def _model_payload(items: Sequence[DomainModel]) -> list[dict[str, object]]:
    return [item.model_dump(mode="json") for item in items]


def run_fhir_pipeline(
    *,
    definition: FormDefinition,
    response_payload: bytes,
    establishment_id: str,
    source_system_id: str,
    batch_id: str,
    patient_pseudonym: str,
    definition_object_key: str,
    response_object_key: str,
    mapping_release: MappingReleaseArtifact,
    signer: ReleaseSigner,
    evaluated_at: datetime,
) -> PipelineResult:
    """Execute canonicalization, exact mapping, quality, OMOP, lineage, and catalog stages."""
    if not verify_mapping_release(mapping_release, signer):
        raise DomainError("INVALID_MAPPING_SIGNATURE", "Mapping release signature is invalid")
    adapter = FhirR4Adapter()
    canonical = adapter.parse_response(
        definition,
        response_payload,
        establishment_id=establishment_id,
        patient_pseudonym=patient_pseudonym,
        evidence_object_key=response_object_key,
    )
    source_checksums = (
        content_hash(definition.model_dump(mode="json")),
        sha256_hex(response_payload),
    )
    manifest = SourceManifest(
        manifest_id=deterministic_uuid(
            "source-manifest",
            establishment_id,
            source_system_id,
            batch_id,
            *source_checksums,
        ),
        establishment_id=establishment_id,
        source_system_id=source_system_id,
        batch_id=batch_id,
        source_period_start=evaluated_at.date(),
        source_period_end=evaluated_at.date(),
        object_keys=(definition_object_key, response_object_key),
        object_checksums=source_checksums,
        record_count=1,
        connector_version=adapter.connector_version,
        schema_version="canonical-answer/1.0.0",
        created_at=evaluated_at,
    )
    standardizer = Standardizer(mapping_release)
    quality_engine = QualityEngine()
    decisions = tuple(
        quality_engine.evaluate(
            event,
            standardizer.standardize(event),
            evaluated_at=evaluated_at,
        )
        for event in canonical
    )
    facts = tuple(
        publish_event(decision.event)
        for decision in decisions
        if decision.decision == PublicationDecision.PUBLISH and decision.event is not None
    )
    lineage: list[dict[str, str]] = []
    fact_by_event = {str(fact.clinical_event_id): fact for fact in facts}
    for canonical_event, decision in zip(canonical, decisions, strict=True):
        canonical_id = f"canonical:{canonical_event.event_id}"
        lineage.append(
            {
                "source": f"raw:{response_object_key}",
                "target": canonical_id,
                "relation": "canonicalized-as",
            }
        )
        lineage.append(
            {
                "source": canonical_id,
                "target": f"mapping:{mapping_release.release_id}",
                "relation": "evaluated-against",
            }
        )
        quality_id = f"quality:{canonical_event.event_id}:{decision.decision}"
        lineage.append(
            {
                "source": f"mapping:{mapping_release.release_id}",
                "target": quality_id,
                "relation": "quality-evaluated",
            }
        )
        if decision.event is not None:
            fact = fact_by_event.get(str(decision.event.clinical_event_id))
            if fact is not None:
                omop_id = f"omop:{fact.table}:{fact.fact_id}"
                lineage.append(
                    {
                        "source": quality_id,
                        "target": omop_id,
                        "relation": "published-as",
                    }
                )
                lineage.append(
                    {
                        "source": omop_id,
                        "target": f"catalog:{establishment_id}:{batch_id}",
                        "relation": "summarized-in",
                    }
                )
    state_counts = Counter(str(event.state) for event in canonical)
    decision_counts = Counter(str(decision.decision) for decision in decisions)
    catalog_summary: dict[str, object] = {
        "establishment_id": establishment_id,
        "batch_id": batch_id,
        "answer_state_counts": dict(sorted(state_counts.items())),
        "publication_decision_counts": dict(sorted(decision_counts.items())),
        "observed_answer_count": len(canonical),
        "published_fact_count": len(facts),
    }
    canonical_checksum = content_hash(_model_payload(canonical))
    quality_checksum = content_hash(_model_payload(decisions))
    omop_checksum = content_hash(_model_payload(facts))
    lineage_checksum = content_hash(lineage)
    catalog_checksum = content_hash(catalog_summary)
    checksums = PipelineChecksums(
        canonical_sha256=canonical_checksum,
        quality_sha256=quality_checksum,
        omop_sha256=omop_checksum,
        lineage_sha256=lineage_checksum,
        catalog_sha256=catalog_checksum,
        combined_sha256=content_hash(
            {
                "source_manifest": manifest.model_dump(mode="json"),
                "canonical": canonical_checksum,
                "quality": quality_checksum,
                "omop": omop_checksum,
                "lineage": lineage_checksum,
                "catalog": catalog_checksum,
            }
        ),
    )
    return PipelineResult(
        source_manifest=manifest,
        canonical_events=canonical,
        quality_decisions=decisions,
        omop_facts=facts,
        published_count=decision_counts[PublicationDecision.PUBLISH],
        quarantined_count=decision_counts[PublicationDecision.QUARANTINE],
        omitted_count=decision_counts[PublicationDecision.OMIT],
        lineage=tuple(lineage),
        catalog_summary=catalog_summary,
        checksums=checksums,
    )


def persist_pipeline_artifacts(
    result: PipelineResult,
    object_store: ObjectStore,
    *,
    canonical_bucket: str,
    partition_rows: int = 50_000,
) -> PipelineArtifactSet:
    """Write bounded Parquet plus semantic artifacts to versioned object storage."""
    manifest = result.source_manifest
    fingerprint = (
        result.canonical_events[0].source_fingerprint
        if result.canonical_events
        else result.checksums.canonical_sha256
    )
    period = manifest.source_period_start.strftime("%Y-%m")
    namespace = (
        f"pipeline/establishment={manifest.establishment_id}/period={period}/"
        f"fingerprint={fingerprint}/batch={manifest.batch_id}"
    )
    stored_manifest = object_store.put_immutable(
        bucket=canonical_bucket,
        namespace=f"{namespace}/manifests",
        content=canonical_json_bytes(manifest.model_dump(mode="json")),
        media_type="application/json",
    )
    parquet_keys: list[str] = []
    with TemporaryDirectory(prefix="ehrfs-canonical-") as temporary:
        partitions = CanonicalParquetWriter(Path(temporary), partition_rows=partition_rows).write(
            result.canonical_events,
            establishment_id=manifest.establishment_id,
            batch_id=manifest.batch_id,
            fingerprint=fingerprint,
            period=period,
        )
        for partition in partitions:
            stored = object_store.put_immutable(
                bucket=canonical_bucket,
                namespace=f"{namespace}/canonical",
                content=partition.path.read_bytes(),
                media_type="application/vnd.apache.parquet",
            )
            parquet_keys.append(stored.key)

    def store_json(stage: str, value: object) -> str:
        stored = object_store.put_immutable(
            bucket=canonical_bucket,
            namespace=f"{namespace}/{stage}",
            content=canonical_json_bytes(value),
            media_type="application/json",
        )
        return stored.key

    return PipelineArtifactSet(
        source_manifest_key=stored_manifest.key,
        canonical_parquet_keys=tuple(parquet_keys),
        quality_key=store_json("quality", _model_payload(result.quality_decisions)),
        omop_key=store_json("omop", _model_payload(result.omop_facts)),
        lineage_key=store_json("lineage", result.lineage),
        catalog_key=store_json("catalog", result.catalog_summary),
    )
