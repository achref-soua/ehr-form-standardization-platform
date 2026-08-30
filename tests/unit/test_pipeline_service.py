from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest

from ehrfs.demo import allergy_form, demo_mapping_artifact, demo_response_payload
from ehrfs.domain.errors import DomainError
from ehrfs.pipeline.service import PipelineResult, persist_pipeline_artifacts, run_fhir_pipeline
from ehrfs.security.signing import ReleaseSigner
from ehrfs.storage.objects import StoredObject

EVALUATED_AT = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


def _run(version: str, signer: ReleaseSigner, *, mapping_version: str = "3") -> PipelineResult:
    artifact = demo_mapping_artifact(
        signer,
        version=mapping_version,
        release_id=f"mapping-pipeline-v{mapping_version}",
    )
    return run_fhir_pipeline(
        definition=allergy_form(version),
        response_payload=demo_response_payload(version),
        establishment_id="site-a",
        source_system_id="site-a-ehr",
        batch_id=f"pipeline-v{version}",
        patient_pseudonym="p_pipeline_test",
        definition_object_key=f"raw/forms/v{version}",
        response_object_key=f"raw/responses/v{version}",
        mapping_release=artifact,
        signer=signer,
        evaluated_at=EVALUATED_AT,
    )


def test_structured_allergy_pipeline_is_complete_and_deterministic() -> None:
    signer = ReleaseSigner.generate()
    first = _run("3", signer)
    second = _run("3", signer)

    assert first == second
    assert first.published_count == 1
    assert first.omitted_count == 1
    assert first.quarantined_count == 0
    assert len(first.canonical_events) == 2
    assert len(first.omop_facts) == 1
    assert first.checksums == second.checksums
    relations = {edge["relation"] for edge in first.lineage}
    assert relations == {
        "canonicalized-as",
        "evaluated-against",
        "quality-evaluated",
        "published-as",
        "summarized-in",
    }


def test_unknown_version_quarantines_until_its_exact_mapping_is_released() -> None:
    signer = ReleaseSigner.generate()
    unknown = _run("4", signer, mapping_version="3")
    released = _run("4", signer, mapping_version="4")

    assert unknown.quarantined_count == 1 and unknown.published_count == 0
    assert released.quarantined_count == 0 and released.published_count == 1
    assert unknown.checksums.combined_sha256 != released.checksums.combined_sha256


def test_pipeline_rejects_a_mapping_with_invalid_signature() -> None:
    signer = ReleaseSigner.generate()
    artifact = demo_mapping_artifact(signer).model_copy(update={"signature_base64": "invalid"})
    with pytest.raises(DomainError, match="signature"):
        run_fhir_pipeline(
            definition=allergy_form(),
            response_payload=demo_response_payload(),
            establishment_id="site-a",
            source_system_id="site-a-ehr",
            batch_id="invalid-signature",
            patient_pseudonym="p_pipeline_test",
            definition_object_key="raw/form",
            response_object_key="raw/response",
            mapping_release=artifact,
            signer=signer,
            evaluated_at=EVALUATED_AT,
        )


class MemoryStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_immutable(
        self, *, bucket: str, namespace: str, content: bytes, media_type: str
    ) -> StoredObject:
        key = f"{namespace}/{len(self.objects)}"
        self.objects[f"{bucket}/{key}"] = content
        return StoredObject(bucket, key, "a" * 64, len(content), media_type)


def test_pipeline_persists_bounded_parquet_and_each_semantic_stage() -> None:
    signer = ReleaseSigner.generate()
    result = _run("3", signer)
    store = MemoryStore()

    artifacts = persist_pipeline_artifacts(
        result,
        cast(Any, store),
        canonical_bucket="canonical",
        partition_rows=1,
    )

    assert len(artifacts.canonical_parquet_keys) == 2
    assert len(store.objects) == 7
    assert all(store.objects.values())
