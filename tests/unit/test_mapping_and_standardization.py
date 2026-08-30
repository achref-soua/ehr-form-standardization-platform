from __future__ import annotations

from datetime import datetime

from ehrfs.domain.enums import AnswerState
from ehrfs.domain.identity import deterministic_uuid
from ehrfs.domain.models import CanonicalAnswerEvent, EvidenceReference, FormDefinition
from ehrfs.fingerprinting.service import fingerprint_form
from ehrfs.mapping.models import MappingEntry, MappingReleaseArtifact, VocabularyRelease
from ehrfs.mapping.releases import create_mapping_release, verify_mapping_release
from ehrfs.mapping.resolver import MappingResolver, ResolutionLevel
from ehrfs.security.signing import ReleaseSigner
from ehrfs.standardization.service import Standardizer


def _answer(
    form: FormDefinition,
    evidence: EvidenceReference,
    fixed_time: datetime,
    *,
    state: AnswerState = AnswerState.EXPLICITLY_ABSENT,
    value: str | None = None,
) -> CanonicalAnswerEvent:
    fingerprints = fingerprint_form(form)
    return CanonicalAnswerEvent(
        event_id=deterministic_uuid("test", "answer"),
        establishment_id="site-a",
        patient_pseudonym="p_123",
        form_id=form.form_id,
        form_version=form.version,
        source_fingerprint=fingerprints.source,
        compatibility_fingerprint=fingerprints.compatibility,
        item_path="Q1",
        state=state,
        value=value,
        raw_value=value or "Non",
        authored_at=fixed_time,
        evidence=(evidence,),
    )


def _release(
    mapping: MappingEntry,
    vocabulary: VocabularyRelease,
    fixed_time: datetime,
) -> tuple[ReleaseSigner, MappingReleaseArtifact]:
    signer = ReleaseSigner.generate()
    release = create_mapping_release(
        parent_release_id=None,
        vocabulary_release=vocabulary,
        entries=(mapping,),
        authored_by="engineer@example.test",
        approved_by="steward@example.test",
        approved_at=fixed_time,
        signer=signer,
    )
    return signer, release


def test_mapping_release_is_signed_and_verifiable(
    allergy_mapping: MappingEntry,
    vocabulary_release: VocabularyRelease,
    fixed_time: datetime,
) -> None:
    signer, release = _release(allergy_mapping, vocabulary_release, fixed_time)
    assert release.has_valid_checksum()
    assert verify_mapping_release(release, signer)


def test_exact_source_mapping_resolves_before_compatibility(
    allergy_form: FormDefinition,
    allergy_mapping: MappingEntry,
    vocabulary_release: VocabularyRelease,
    evidence: EvidenceReference,
    fixed_time: datetime,
) -> None:
    _, release = _release(allergy_mapping, vocabulary_release, fixed_time)
    resolved = MappingResolver(release).resolve(_answer(allergy_form, evidence, fixed_time))
    assert resolved is not None
    assert resolved.level == ResolutionLevel.SOURCE_FINGERPRINT


def test_negative_allergy_standardizes_without_collapsing_state(
    allergy_form: FormDefinition,
    allergy_mapping: MappingEntry,
    vocabulary_release: VocabularyRelease,
    evidence: EvidenceReference,
    fixed_time: datetime,
) -> None:
    _, release = _release(allergy_mapping, vocabulary_release, fixed_time)
    result = Standardizer(release).standardize(_answer(allergy_form, evidence, fixed_time))
    assert result.succeeded
    assert result.event is not None
    assert result.event.state == AnswerState.EXPLICITLY_ABSENT
    assert result.event.value is None
