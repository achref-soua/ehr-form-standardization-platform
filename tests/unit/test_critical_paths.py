from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from ehrfs.demo import allergy_form
from ehrfs.domain.enums import (
    AnswerState,
    FailureReason,
    OmopDomain,
    PublicationDecision,
)
from ehrfs.domain.errors import DomainError
from ehrfs.domain.identity import content_hash, deterministic_uuid
from ehrfs.domain.models import (
    CanonicalAnswerEvent,
    EvidenceReference,
    FormDefinition,
    ItemDefinition,
)
from ehrfs.fingerprinting.service import fingerprint_form
from ehrfs.mapping.models import (
    MappingEntry,
    MappingReleaseArtifact,
    MappingScope,
    MappingTarget,
    MappingTestVector,
    UnitRule,
    VocabularyRelease,
)
from ehrfs.mapping.releases import (
    create_mapping_release,
    validate_mapping_tests,
    verify_mapping_release,
)
from ehrfs.mapping.resolver import MappingResolver, ResolutionLevel
from ehrfs.omop.publisher import OmopFact, publish_event
from ehrfs.quality.engine import QualityEngine
from ehrfs.security.signing import ReleaseSigner
from ehrfs.standardization.conversion import convert_unit
from ehrfs.standardization.models import ClinicalEvent, StandardizationResult
from ehrfs.standardization.service import Standardizer


def _release(
    entries: tuple[MappingEntry, ...],
    vocabulary: VocabularyRelease,
    fixed_time: datetime,
) -> tuple[ReleaseSigner, MappingReleaseArtifact]:
    signer = ReleaseSigner.generate()
    artifact = create_mapping_release(
        parent_release_id="mapping-parent",
        vocabulary_release=vocabulary,
        entries=entries,
        authored_by="engineer@example.test",
        approved_by="steward@example.test",
        approved_at=fixed_time,
        signer=signer,
    )
    return signer, artifact


def _answer(
    form: FormDefinition,
    evidence: EvidenceReference,
    fixed_time: datetime,
    *,
    value: str | int | float | bool | Decimal | None = None,
    state: AnswerState = AnswerState.PRESENT,
    unit: str | None = None,
    item_path: str = "Q1",
) -> CanonicalAnswerEvent:
    fingerprints = fingerprint_form(form)
    return CanonicalAnswerEvent(
        event_id=deterministic_uuid("critical-answer", item_path, str(value), state),
        establishment_id="site-a",
        patient_pseudonym="patient",
        encounter_pseudonym="encounter",
        form_id=form.form_id,
        form_version=form.version,
        source_fingerprint=fingerprints.source,
        compatibility_fingerprint=fingerprints.compatibility,
        item_path=item_path,
        state=state,
        value=value,
        raw_value=value,
        unit=unit,
        authored_at=fixed_time,
        evidence=(evidence,),
    )


def _mapping(
    form: FormDefinition,
    mapping_id: str,
    *,
    establishment_id: str | None = None,
    source_fingerprint: str | None = None,
    compatibility_fingerprint: str | None = None,
    value_map: dict[str, str] | None = None,
    unit_rule: UnitRule | None = None,
) -> MappingEntry:
    fingerprints = fingerprint_form(form)
    vector_source: str | int = 1000 if unit_rule else "known"
    vector_source_unit = unit_rule.source_unit if unit_rule else None
    vector_expected = (
        convert_unit(vector_source, unit_rule)
        if unit_rule
        else ((value_map or {}).get("known", "known"))
    )
    vector_expected_unit = unit_rule.target_unit if unit_rule else None
    return MappingEntry(
        mapping_id=mapping_id,
        scope=MappingScope(
            ehr_product=form.ehr_product,
            form_family=form.form_family,
            item_path="Q1",
            establishment_id=establishment_id,
            source_fingerprint=(
                fingerprints.source if source_fingerprint is None else source_fingerprint
            ),
            compatibility_fingerprint=(
                fingerprints.compatibility
                if compatibility_fingerprint is None
                else compatibility_fingerprint
            ),
        ),
        declared_source_type="string",
        target=MappingTarget(
            domain=OmopDomain.MEASUREMENT if unit_rule else OmopDomain.OBSERVATION,
            concept_id=2_000_001,
            concept_code="DEMO",
            concept_name="Demo concept",
            vocabulary_id="EHRFS_DEMO",
            standard_concept=True,
        ),
        value_map=value_map or {},
        unit_rule=unit_rule,
        tests=(
            MappingTestVector(
                name="critical vector",
                source_state=AnswerState.PRESENT,
                source_value=vector_source,
                source_unit=vector_source_unit,
                expected_state=AnswerState.PRESENT,
                expected_value=vector_expected,
                expected_unit=vector_expected_unit,
            ),
        ),
    )


def test_mapping_schema_release_and_resolver_precedence(
    allergy_form: FormDefinition,
    vocabulary_release: VocabularyRelease,
    evidence: EvidenceReference,
    fixed_time: datetime,
) -> None:
    with pytest.raises(ValidationError, match="exact source or compatibility"):
        MappingScope(ehr_product="x", form_family="f", item_path="Q")
    with pytest.raises(ValidationError, match="executable test vectors"):
        _mapping(allergy_form, "empty").model_copy(update={"tests": ()}).model_validate(
            _mapping(allergy_form, "empty").model_dump() | {"tests": ()}
        )

    generic = _mapping(allergy_form, "generic")
    site = _mapping(allergy_form, "site", establishment_id="site-a")
    signer, artifact = _release((generic, site), vocabulary_release, fixed_time)
    answer = _answer(allergy_form, evidence, fixed_time, value="known")
    resolved = MappingResolver(artifact).resolve(answer)
    assert resolved is not None and resolved.level == ResolutionLevel.SITE_OVERRIDE

    wrong_site = site.model_copy(
        update={"scope": site.scope.model_copy(update={"establishment_id": "site-b"})}
    )
    _, fallback_artifact = _release((generic, wrong_site), vocabulary_release, fixed_time)
    fallback = MappingResolver(fallback_artifact).resolve(answer)
    assert fallback is not None and fallback.level == ResolutionLevel.SOURCE_FINGERPRINT

    wrong_site_fingerprint = site.model_copy(
        update={"scope": site.scope.model_copy(update={"source_fingerprint": "wrong"})}
    )
    _, fallback_artifact = _release(
        (generic, wrong_site_fingerprint), vocabulary_release, fixed_time
    )
    assert MappingResolver(fallback_artifact).resolve(answer) is not None

    compatibility_entry = _mapping(
        allergy_form,
        "compatibility",
        source_fingerprint="different",
    )
    _, compatibility_artifact = _release((compatibility_entry,), vocabulary_release, fixed_time)
    compatibility = MappingResolver(compatibility_artifact).resolve(answer)
    assert compatibility is not None
    assert compatibility.level == ResolutionLevel.COMPATIBILITY_FINGERPRINT

    assert (
        MappingResolver(artifact).resolve(answer.model_copy(update={"item_path": "missing"}))
        is None
    )
    no_match_entry = _mapping(
        allergy_form,
        "no-match",
        source_fingerprint="different-source",
        compatibility_fingerprint="different-compatibility",
    )
    _, no_match_artifact = _release((no_match_entry,), vocabulary_release, fixed_time)
    assert MappingResolver(no_match_artifact).resolve(answer) is None
    duplicate = generic.model_copy(update={"mapping_id": "generic-2"})
    _, ambiguous_artifact = _release((generic, duplicate), vocabulary_release, fixed_time)
    with pytest.raises(DomainError, match="Multiple mappings"):
        MappingResolver(ambiguous_artifact).resolve(answer)
    with pytest.raises(DomainError, match="checksum"):
        MappingResolver(artifact.model_copy(update={"payload_checksum_sha256": "f" * 64}))

    assert verify_mapping_release(artifact, signer)
    assert not verify_mapping_release(
        artifact.model_copy(update={"payload_checksum_sha256": "f" * 64}), signer
    )
    other_signer = ReleaseSigner.generate()
    assert not verify_mapping_release(artifact, other_signer)
    assert not verify_mapping_release(
        artifact.model_copy(update={"signature_base64": "invalid"}), signer
    )


def test_mapping_release_model_rejects_same_maker_and_duplicates(
    allergy_form: FormDefinition,
    vocabulary_release: VocabularyRelease,
    fixed_time: datetime,
) -> None:
    entry = _mapping(allergy_form, "entry")
    _, artifact = _release((entry,), vocabulary_release, fixed_time)
    payload = artifact.model_dump()
    payload["approved_by"] = payload["authored_by"]
    with pytest.raises(ValidationError, match="distinct author"):
        MappingReleaseArtifact.model_validate(payload)
    payload = artifact.model_dump()
    payload["entries"] = [entry.model_dump(), entry.model_dump()]
    with pytest.raises(ValidationError, match="Mapping IDs"):
        MappingReleaseArtifact.model_validate(payload)

    failing = entry.model_copy(
        update={"tests": (entry.tests[0].model_copy(update={"expected_value": "incorrect"}),)}
    )
    with pytest.raises(DomainError, match="expected"):
        validate_mapping_tests((failing,))


def test_mapping_release_vectors_cover_every_declarative_state_transition(
    allergy_form: FormDefinition,
) -> None:
    base = _mapping(allergy_form, "state-vectors")
    missing = base.model_copy(
        update={
            "missing_value_codes": ("missing",),
            "tests": (
                MappingTestVector(
                    name="missing code",
                    source_state=AnswerState.PRESENT,
                    source_value="missing",
                    expected_state=AnswerState.UNKNOWN,
                ),
            ),
        }
    )
    negative = base.model_copy(
        update={
            "negative_value_codes": ("none",),
            "tests": (
                MappingTestVector(
                    name="negative code",
                    source_state=AnswerState.PRESENT,
                    source_value="none",
                    expected_state=AnswerState.EXPLICITLY_ABSENT,
                ),
            ),
        }
    )
    present_without_value = base.model_copy(
        update={
            "tests": (
                MappingTestVector(
                    name="present without value",
                    source_state=AnswerState.PRESENT,
                    expected_state=AnswerState.PRESENT,
                ),
            ),
        }
    )
    non_present = base.model_copy(
        update={
            "tests": (
                MappingTestVector(
                    name="explicit absence clears payload",
                    source_state=AnswerState.EXPLICITLY_ABSENT,
                    source_value="ignored",
                    source_unit="ignored-unit",
                    expected_state=AnswerState.EXPLICITLY_ABSENT,
                ),
            ),
        }
    )
    unit_rule = UnitRule(source_unit="g", target_unit="kg", multiplier="0.001")
    unit_mismatch = base.model_copy(
        update={
            "unit_rule": unit_rule,
            "tests": (
                MappingTestVector(
                    name="mismatched unit",
                    source_state=AnswerState.PRESENT,
                    source_value=1000,
                    source_unit="lb",
                    expected_state=AnswerState.PRESENT,
                    expected_unit="lb",
                ),
            ),
        }
    )
    unmapped_unit_value = base.model_copy(
        update={
            "value_map": {"mapped": 1},
            "unit_rule": unit_rule,
            "tests": (
                MappingTestVector(
                    name="unmapped quantity",
                    source_state=AnswerState.PRESENT,
                    source_value="unknown",
                    source_unit="g",
                    expected_state=AnswerState.PRESENT,
                    expected_unit="kg",
                ),
            ),
        }
    )

    validate_mapping_tests(
        (
            missing,
            negative,
            present_without_value,
            non_present,
            unit_mismatch,
            unmapped_unit_value,
        )
    )


def test_mapping_release_identity_binds_every_governance_input(
    allergy_form: FormDefinition,
    vocabulary_release: VocabularyRelease,
    fixed_time: datetime,
) -> None:
    entry = _mapping(allergy_form, "identity-bound")
    signer = ReleaseSigner.generate()
    artifact = create_mapping_release(
        parent_release_id="mapping-parent",
        vocabulary_release=vocabulary_release,
        entries=(entry,),
        authored_by="engineer@example.test",
        approved_by="steward@example.test",
        approved_at=fixed_time,
        signer=signer,
    )
    identity_payload = {
        "schema_version": "1.0",
        "parent_release_id": "mapping-parent",
        "vocabulary_release": vocabulary_release.model_dump(mode="json"),
        "entries": [entry.model_dump(mode="json")],
        "authored_by": "engineer@example.test",
        "approved_by": "steward@example.test",
        "approved_at": fixed_time.isoformat(),
    }
    assert artifact.release_id == f"mapping_{content_hash(identity_payload)[:16]}"
    assert artifact.parent_release_id == "mapping-parent"
    assert artifact.vocabulary_release == vocabulary_release
    assert artifact.entries == (entry,)
    assert artifact.authored_by == "engineer@example.test"
    assert artifact.approved_by == "steward@example.test"
    assert artifact.approved_at == fixed_time
    assert artifact.signing_key_id == signer.key_id
    assert artifact.signature_base64 not in {"pending", "PENDING"}
    assert verify_mapping_release(artifact, signer)

    def candidate_id(
        *,
        parent: str = "mapping-parent",
        candidate_entries: tuple[MappingEntry, ...] = (entry,),
        author: str = "engineer@example.test",
        approver: str = "steward@example.test",
        approved_at: datetime = fixed_time,
    ) -> str:
        return create_mapping_release(
            parent_release_id=parent,
            vocabulary_release=vocabulary_release,
            entries=candidate_entries,
            authored_by=author,
            approved_by=approver,
            approved_at=approved_at,
            signer=signer,
        ).release_id

    changed_release_ids = (
        candidate_id(parent="mapping-other"),
        candidate_id(
            candidate_entries=(entry.model_copy(update={"mapping_id": "identity-other"}),)
        ),
        candidate_id(author="engineer-two@example.test"),
        candidate_id(approver="steward-two@example.test"),
        candidate_id(approved_at=fixed_time.replace(microsecond=1)),
    )
    assert all(release_id != artifact.release_id for release_id in changed_release_ids)


def test_standardizer_failures_conversion_and_state_clearing(
    allergy_form: FormDefinition,
    vocabulary_release: VocabularyRelease,
    evidence: EvidenceReference,
    fixed_time: datetime,
) -> None:
    mapped_entry = _mapping(allergy_form, "values", value_map={"known": "mapped"})
    _, value_artifact = _release((mapped_entry,), vocabulary_release, fixed_time)
    standardizer = Standardizer(value_artifact)
    unknown_mapping = standardizer.standardize(
        _answer(allergy_form, evidence, fixed_time, value="known", item_path="other")
    )
    assert unknown_mapping.failures == (FailureReason.UNKNOWN_MAPPING,)
    unknown_value = standardizer.standardize(
        _answer(allergy_form, evidence, fixed_time, value="unknown")
    )
    assert unknown_value.failures == (FailureReason.UNKNOWN_LOCAL_VALUE,)
    success = standardizer.standardize(_answer(allergy_form, evidence, fixed_time, value="known"))
    assert success.event is not None and success.event.value == "mapped"
    assert success.succeeded

    rule = UnitRule(source_unit="g", target_unit="kg", multiplier="0.001")
    unit_entry = _mapping(allergy_form, "unit", unit_rule=rule)
    _, unit_artifact = _release((unit_entry,), vocabulary_release, fixed_time)
    unit_standardizer = Standardizer(unit_artifact)
    mismatch = unit_standardizer.standardize(
        _answer(allergy_form, evidence, fixed_time, value=1000, unit="lb")
    )
    assert mismatch.failures == (FailureReason.INVALID_UNIT,)
    invalid = unit_standardizer.standardize(
        _answer(allergy_form, evidence, fixed_time, value=True, unit="g")
    )
    assert invalid.failures == (FailureReason.INVALID_UNIT,)
    converted = unit_standardizer.standardize(
        _answer(allergy_form, evidence, fixed_time, value=2500, unit="g")
    )
    assert converted.event is not None
    assert converted.event.value == Decimal("2.5") and converted.event.unit == "kg"

    cleared_entry = mapped_entry.model_copy(
        update={"state_map": {AnswerState.EXPLICITLY_ABSENT: AnswerState.UNKNOWN}}
    )
    _, cleared_artifact = _release((cleared_entry,), vocabulary_release, fixed_time)
    cleared = Standardizer(cleared_artifact).standardize(
        _answer(
            allergy_form,
            evidence,
            fixed_time,
            value=None,
            state=AnswerState.EXPLICITLY_ABSENT,
            unit="kg",
        )
    )
    assert cleared.event is not None
    assert cleared.event.state == AnswerState.UNKNOWN
    assert cleared.event.value is None and cleared.event.unit is None


def _clinical_event(
    evidence: EvidenceReference,
    fixed_time: datetime,
    *,
    value: str | int | bool | Decimal | None,
    state: AnswerState,
    domain: OmopDomain = OmopDomain.OBSERVATION,
) -> ClinicalEvent:
    return ClinicalEvent(
        clinical_event_id=deterministic_uuid("clinical", str(value), state, domain),
        canonical_event_id=deterministic_uuid("canonical", str(value), state, domain),
        establishment_id="site-a",
        patient_pseudonym="patient",
        occurred_at=fixed_time,
        state=state,
        value=value,
        unit="kg",
        target_domain=domain,
        target_concept_id=2_000_001,
        target_concept_code="DEMO",
        target_concept_name="Demo",
        target_vocabulary_id="EHRFS_DEMO",
        source_value=str(value),
        mapping_id="mapping",
        mapping_release_id="release",
        vocabulary_release_id="vocabulary",
        evidence=(evidence,),
    )


def test_quality_decisions_and_omop_value_columns(
    evidence: EvidenceReference,
    fixed_time: datetime,
) -> None:
    canonical = CanonicalAnswerEvent(
        event_id=deterministic_uuid("quality", "canonical"),
        establishment_id="site-a",
        patient_pseudonym="patient",
        form_id="form",
        form_version="1",
        source_fingerprint="a" * 64,
        compatibility_fingerprint="b" * 64,
        item_path="Q1",
        state=AnswerState.PRESENT,
        value="yes",
        authored_at=fixed_time,
        evidence=(evidence,),
    )
    event = _clinical_event(evidence, fixed_time, value="yes", state=AnswerState.PRESENT)
    published = QualityEngine().evaluate(
        canonical, StandardizationResult(event=event), evaluated_at=fixed_time
    )
    assert published.decision == PublicationDecision.PUBLISH
    assert all(result.passed for result in published.results)

    missing_mapping = QualityEngine().evaluate(
        canonical,
        StandardizationResult(failures=(FailureReason.UNKNOWN_MAPPING,)),
        evaluated_at=fixed_time,
    )
    assert missing_mapping.decision == PublicationDecision.QUARANTINE
    assert missing_mapping.failures == (FailureReason.UNKNOWN_MAPPING,)
    missing_without_reason = QualityEngine().evaluate(
        canonical, StandardizationResult(), evaluated_at=fixed_time
    )
    assert missing_without_reason.decision == PublicationDecision.QUARANTINE
    assert missing_without_reason.failures == (FailureReason.UNKNOWN_MAPPING,)

    no_evidence = canonical.model_copy(update={"evidence": ()})
    provenance = QualityEngine().evaluate(
        no_evidence, StandardizationResult(event=event), evaluated_at=fixed_time
    )
    assert FailureReason.MISSING_PROVENANCE in provenance.failures
    invalid = canonical.model_copy(update={"state": AnswerState.INVALID, "value": None})
    invalid_decision = QualityEngine().evaluate(
        invalid, StandardizationResult(event=event), evaluated_at=fixed_time
    )
    assert invalid_decision.decision == PublicationDecision.QUARANTINE
    nonstandard = QualityEngine().evaluate(
        canonical,
        StandardizationResult(event=event.model_copy(update={"target_concept_id": 0})),
        evaluated_at=fixed_time,
    )
    assert FailureReason.OMOP_CONFORMANCE_FAILURE in nonstandard.failures

    cases = (
        (_clinical_event(evidence, fixed_time, value=True, state=AnswerState.PRESENT), "true"),
        (_clinical_event(evidence, fixed_time, value=False, state=AnswerState.PRESENT), "false"),
        (_clinical_event(evidence, fixed_time, value=12, state=AnswerState.PRESENT), Decimal("12")),
        (_clinical_event(evidence, fixed_time, value="text", state=AnswerState.PRESENT), "text"),
        (
            _clinical_event(evidence, fixed_time, value=None, state=AnswerState.EXPLICITLY_ABSENT),
            AnswerState.EXPLICITLY_ABSENT,
        ),
        (_clinical_event(evidence, fixed_time, value=None, state=AnswerState.UNKNOWN), None),
    )
    for clinical, expected in cases:
        fact = publish_event(clinical)
        observed = (
            fact.value_as_number if fact.value_as_number is not None else fact.value_as_string
        )
        assert observed == expected
    with pytest.raises(ValidationError, match="at most one"):
        OmopFact(
            fact_id=deterministic_uuid("fact", "invalid"),
            table="observation",
            person_source_value="patient",
            concept_id=1,
            event_date=fixed_time.date(),
            event_datetime=fixed_time,
            value_as_number=Decimal("1"),
            value_as_string="one",
            clinical_event_id=event.clinical_event_id,
        )


def test_fingerprint_unordered_forms_and_nested_unordered_children() -> None:
    a = ItemDefinition(item_id="A", path="A", label=" A   label ", data_type="string", order=9)
    b = ItemDefinition(item_id="B", path="B", label="B", data_type="string", order=1)
    first = allergy_form().model_copy(update={"source_order_semantic": False, "items": (a, b)})
    second = first.model_copy(update={"items": (b, a)})
    assert fingerprint_form(first).compatibility == fingerprint_form(second).compatibility

    group = ItemDefinition(
        item_id="G",
        path="G",
        label="Group",
        data_type="group",
        order=0,
        order_semantic=False,
        children=(a, b),
    )
    reversed_group = group.model_copy(update={"children": (b, a)})
    nested_first = first.model_copy(update={"items": (group,)})
    nested_second = first.model_copy(update={"items": (reversed_group,)})
    assert (
        fingerprint_form(nested_first).compatibility
        == fingerprint_form(nested_second).compatibility
    )
