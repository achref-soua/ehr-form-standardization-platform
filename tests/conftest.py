from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ehrfs.domain.enums import AnswerState, ExtractionMethod, OmopDomain
from ehrfs.domain.identity import sha256_hex
from ehrfs.domain.models import EvidenceReference, FormDefinition, ItemDefinition, ValueOption
from ehrfs.fingerprinting.service import fingerprint_form
from ehrfs.mapping.models import (
    MappingEntry,
    MappingScope,
    MappingTarget,
    MappingTestVector,
    VocabularyRelease,
)


@pytest.fixture
def evidence() -> EvidenceReference:
    payload = b'{"resourceType":"QuestionnaireResponse"}'
    return EvidenceReference(
        object_key="raw/site-a/response-991.json",
        checksum_sha256=sha256_hex(payload),
        media_type="application/fhir+json",
        json_pointer="/item/0",
        extraction_method=ExtractionMethod.FHIR,
        extractor_version="test/1.0",
    )


@pytest.fixture
def allergy_form() -> FormDefinition:
    return FormDefinition(
        ehr_product="DemoEHR",
        ehr_version="2026.1",
        form_id="ATCD_ALLERGIES",
        form_family="allergy-history",
        version="3",
        title="Antécédents allergiques",
        items=(
            ItemDefinition(
                item_id="Q1",
                path="Q1",
                label="Allergie connue ?",
                data_type="coding",
                order=0,
                value_options=(
                    ValueOption(code="Oui", display="Oui"),
                    ValueOption(code="Non", display="Non"),
                ),
            ),
        ),
    )


@pytest.fixture
def allergy_mapping(allergy_form: FormDefinition) -> MappingEntry:
    fingerprints = fingerprint_form(allergy_form)
    return MappingEntry(
        mapping_id="map-allergy-q1-v3",
        scope=MappingScope(
            ehr_product="DemoEHR",
            form_family="allergy-history",
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
        state_map={AnswerState.EXPLICITLY_ABSENT: AnswerState.EXPLICITLY_ABSENT},
        tests=(
            MappingTestVector(
                name="negative allergy answer",
                source_state=AnswerState.EXPLICITLY_ABSENT,
                expected_state=AnswerState.EXPLICITLY_ABSENT,
            ),
        ),
    )


@pytest.fixture
def vocabulary_release() -> VocabularyRelease:
    return VocabularyRelease(
        release_id="vocab_demo_2026_08",
        vocabulary_version="EHRFS_DEMO 2026-08",
        source="project-owned non-clinical fixture",
        checksum_sha256="a" * 64,
    )


@pytest.fixture
def fixed_time() -> datetime:
    return datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
