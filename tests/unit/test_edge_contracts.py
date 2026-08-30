from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ehrfs.canonical.conditions import conditions_satisfied
from ehrfs.catalog.coverage import CoverageInputs, calculate_coverage
from ehrfs.config import Settings, get_settings
from ehrfs.documents.assertion import extract_allergy_candidate
from ehrfs.domain.enums import AnswerState, ExtractionMethod, LifecycleStatus
from ehrfs.domain.errors import ConflictError, DomainError, NotFoundError
from ehrfs.domain.models import (
    DisplayCondition,
    EvidenceReference,
    FormDefinition,
    ItemDefinition,
    LifecycleEvent,
    ScalarValue,
    SourceManifest,
    utc_now,
)
from ehrfs.ingestion.fhir import (
    FhirR4Adapter,
    _extract_answer,
    _load_json,
    _parse_answer_option,
    _parse_condition,
)
from ehrfs.ingestion.tabular import TabularAnswer, TabularFormAdapter
from ehrfs.security.pseudonymization import pseudonymize
from ehrfs.security.uploads import normalize_filename, validate_upload


def _json(value: object) -> bytes:
    return json.dumps(value).encode()


def _simple_item(**changes: object) -> dict[str, object]:
    item: dict[str, object] = {"linkId": "Q1", "type": "string", "text": "Question"}
    item.update(changes)
    return item


def test_fhir_definition_supports_bounded_types_options_and_conditions() -> None:
    questionnaire = {
        "resourceType": "Questionnaire",
        "url": "https://example.test/forms/full",
        "version": "7",
        "name": "Fallback name",
        "status": "active",
        "item": [
            {
                "linkId": "Q1",
                "type": "choice",
                "text": "Choice",
                "required": True,
                "answerOption": [
                    {
                        "valueCoding": {
                            "system": "https://example.test/codes",
                            "code": "yes",
                            "display": "Yes",
                        }
                    }
                ],
            },
            {
                "linkId": "Q2",
                "type": "open-choice",
                "repeats": True,
                "answerOption": [{"valueString": "free"}, {"valueInteger": 4}],
                "enableWhen": [
                    {
                        "question": "Q1",
                        "operator": "=",
                        "answerCoding": {"code": "yes"},
                    }
                ],
            },
            {
                "linkId": "G",
                "type": "group",
                "item": [
                    {"linkId": "D", "type": "date"},
                    {"linkId": "DT", "type": "dateTime"},
                    {"linkId": "B", "type": "boolean"},
                    {"linkId": "I", "type": "integer"},
                    {"linkId": "N", "type": "decimal"},
                    {"linkId": "T", "type": "text"},
                ],
            },
        ],
    }
    form = FhirR4Adapter().parse_definition(_json(questionnaire))
    assert form.form_id == questionnaire["url"]
    assert form.title == "Fallback name"
    assert form.items[0].value_options[0].system == "https://example.test/codes"
    assert [option.code for option in form.items[1].value_options] == ["free", "4"]
    assert form.items[1].display_conditions[0].expected == "yes"
    assert len(form.items[2].children) == 6

    fallback = FhirR4Adapter().parse_definition(
        _json({"resourceType": "Questionnaire", "id": "fallback", "item": []})
    )
    assert fallback.form_id == fallback.title == "fallback"
    unknown = FhirR4Adapter().parse_definition(_json({"resourceType": "Questionnaire", "item": []}))
    assert unknown.version == "unversioned"


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"not-json", "JSON object"),
        (_json([]), "JSON object"),
        (_json({"resourceType": "Patient"}), "Expected Questionnaire"),
    ],
)
def test_fhir_resource_validation(payload: bytes, message: str) -> None:
    with pytest.raises(DomainError, match=message):
        _load_json(payload, "Questionnaire")


@pytest.mark.parametrize(
    ("item", "message"),
    [
        ({"type": "string"}, "linkId"),
        (_simple_item(type="reference"), "Unsupported item type"),
        (_simple_item(item={}), "must be a list"),
        (_simple_item(enableWhen={}), "enableWhen must be a list"),
        (_simple_item(answerOption={}), "answerOption must be a list"),
        (_simple_item(answerOption=[{"valueCoding": {}}]), "string code"),
        (_simple_item(answerOption=[{"valueBoolean": True}]), "Unsupported Questionnaire"),
    ],
)
def test_fhir_definition_rejects_ambiguous_item_shapes(
    item: dict[str, object], message: str
) -> None:
    with pytest.raises(DomainError, match=message):
        FhirR4Adapter().parse_definition(
            _json({"resourceType": "Questionnaire", "id": "invalid", "item": [item]})
        )


def test_fhir_option_and_condition_edge_cases() -> None:
    assert _parse_answer_option({"valueCoding": {"code": "x"}}).display == "x"
    paths = {"Q1": "Q1"}
    for fhir_operator, operator in (
        ("!=", "ne"),
        (">", "gt"),
        (">=", "gte"),
        ("<", "lt"),
        ("<=", "lte"),
        ("exists", "exists"),
    ):
        answer_key = "answerBoolean" if fhir_operator == "exists" else "answerInteger"
        expected = True if fhir_operator == "exists" else 2
        condition = _parse_condition(
            {"question": "Q1", "operator": fhir_operator, answer_key: expected}, paths
        )
        assert condition.operator == operator
    invalid_conditions = (
        ({"question": "missing", "answerString": "x"}, "unknown question"),
        ({"question": "Q1", "operator": "~", "answerString": "x"}, "Unsupported"),
        ({"question": "Q1"}, "exactly one"),
        (
            {"question": "Q1", "answerString": "x", "answerInteger": 2},
            "exactly one",
        ),
    )
    for value, message in invalid_conditions:
        with pytest.raises(DomainError, match=message):
            _parse_condition(value, paths)


def test_fhir_answers_and_response_shape_edges() -> None:
    assert _extract_answer({"valueCoding": {"code": "yes"}}) == "yes"
    assert _extract_answer({"valueQuantity": {"value": 1.5}}) == 1.5
    assert _extract_answer({"valueBoolean": False}) is False
    answers_to_reject: tuple[dict[str, Any], ...] = (
        {},
        {"valueString": "x", "valueInteger": 1},
        {"valueCoding": {"display": "missing code"}},
        {"valueQuantity": {"value": []}},
        {"valueCustom": []},
    )
    for answer in answers_to_reject:
        with pytest.raises(DomainError):
            _extract_answer(answer)

    form = FormDefinition(
        ehr_product="FHIR R4",
        ehr_version="4.0.1",
        form_id="multi",
        form_family="multi",
        version="1",
        title="Multi-answer",
        items=(ItemDefinition(item_id="Q1", path="Q1", label="Q1", data_type="string", order=0),),
    )
    response = {
        "resourceType": "QuestionnaireResponse",
        "item": [
            {
                "linkId": "Q1",
                "answer": [{"valueString": "first"}, {"valueString": "second"}],
            }
        ],
    }
    events = FhirR4Adapter().parse_response(
        form,
        _json(response),
        establishment_id="site-a",
        patient_pseudonym="patient",
        evidence_object_key="raw/response.json",
    )
    assert [event.group_instance for event in events] == ["answer:0", "answer:1"]
    assert events[0].authored_at == datetime(1970, 1, 1, tzinfo=UTC)

    invalid_responses: tuple[tuple[dict[str, Any], str], ...] = (
        ({"item": {}}, "QuestionnaireResponse.item"),
        ({"item": [{"answer": []}]}, "linkId"),
        ({"item": [{"linkId": "Q1", "answer": {}}]}, "answers must be a list"),
        ({"item": [{"linkId": "Q1", "item": {}}]}, "must be a list"),
    )
    for fragment, message in invalid_responses:
        with pytest.raises(DomainError, match=message):
            FhirR4Adapter().parse_response(
                form,
                _json({"resourceType": "QuestionnaireResponse", **fragment}),
                establishment_id="site-a",
                patient_pseudonym="patient",
                evidence_object_key="raw/invalid.json",
            )


def test_conditions_cover_every_operator_and_behavior() -> None:
    answers: dict[str, ScalarValue | None] = {
        "present": 5,
        "text": "yes",
        "invalid": "word",
        "none": None,
    }
    conditions = (
        DisplayCondition(source_item_path="present", operator="gt", expected=4),
        DisplayCondition(source_item_path="present", operator="gte", expected=5),
        DisplayCondition(source_item_path="present", operator="lt", expected=6),
        DisplayCondition(source_item_path="present", operator="lte", expected=5),
        DisplayCondition(source_item_path="text", operator="eq", expected="yes"),
        DisplayCondition(source_item_path="text", operator="ne", expected="no"),
        DisplayCondition(source_item_path="present", operator="exists", expected=True),
        DisplayCondition(source_item_path="missing", operator="exists", expected=False),
    )
    assert conditions_satisfied(conditions, answers)
    assert conditions_satisfied((), answers)
    assert conditions_satisfied(
        (
            DisplayCondition(source_item_path="none", operator="gt", expected=1),
            DisplayCondition(source_item_path="text", operator="eq", expected="yes"),
        ),
        answers,
        behavior="any",
    )
    assert not conditions_satisfied(
        (DisplayCondition(source_item_path="invalid", operator="gt", expected=1),), answers
    )
    with pytest.raises(ValueError, match="Unsupported condition behavior"):
        conditions_satisfied(conditions, answers, behavior="xor")


def test_domain_manifest_item_evidence_and_lifecycle_invariants() -> None:
    child = ItemDefinition(item_id="C", path="G/C", label="Child", data_type="string", order=0)
    with pytest.raises(ValidationError, match="Group items require"):
        ItemDefinition(item_id="G", path="G", label="Group", data_type="group", order=0)
    with pytest.raises(ValidationError, match="Only group"):
        ItemDefinition(
            item_id="Q", path="Q", label="Question", data_type="string", order=0, children=(child,)
        )
    with pytest.raises(ValidationError, match="Child item paths"):
        ItemDefinition(
            item_id="G",
            path="G",
            label="Group",
            data_type="group",
            order=0,
            children=(child, child),
        )
    group = ItemDefinition(
        item_id="G", path="G", label="Group", data_type="group", order=0, children=(child,)
    )
    with pytest.raises(ValidationError, match="Every item path"):
        FormDefinition(
            ehr_product="x",
            ehr_version="1",
            form_id="f",
            form_family="f",
            version="1",
            title="f",
            items=(group, child),
        )

    manifest = {
        "manifest_id": uuid4(),
        "establishment_id": "site-a",
        "source_system_id": "source",
        "batch_id": "batch",
        "source_period_start": date(2026, 1, 1),
        "source_period_end": date(2026, 1, 31),
        "object_keys": ("raw/a",),
        "object_checksums": ("a" * 64,),
        "record_count": 1,
        "connector_version": "1",
        "schema_version": "1",
        "created_at": datetime.now(UTC),
    }
    assert SourceManifest(**manifest).record_count == 1
    with pytest.raises(ValidationError, match="exactly one checksum"):
        SourceManifest(**{**manifest, "object_checksums": ()})
    with pytest.raises(ValidationError, match="cannot precede"):
        SourceManifest(
            **{
                **manifest,
                "source_period_start": date(2026, 2, 1),
                "source_period_end": date(2026, 1, 1),
            }
        )

    evidence_values = {
        "object_key": "raw/a",
        "checksum_sha256": "a" * 64,
        "media_type": "application/json",
        "extraction_method": ExtractionMethod.STRUCTURED_FORM,
        "extractor_version": "1",
    }
    with pytest.raises(ValidationError, match="greater than"):
        EvidenceReference(**evidence_values, text_span_start=4, text_span_end=4)
    assert EvidenceReference(**evidence_values, text_span_start=1, text_span_end=2)
    corrected = LifecycleEvent(
        status=LifecycleStatus.CORRECTED,
        occurred_at=datetime.now(UTC),
        source_sequence=2,
        supersedes_event_id=uuid4(),
    )
    assert corrected.supersedes_event_id is not None
    assert utc_now().tzinfo == UTC


def test_security_config_upload_and_pseudonymization_edges(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="Placeholder secrets"):
        Settings(demo_mode=False)
    with pytest.raises(ValidationError, match="heartbeat"):
        Settings(job_heartbeat_seconds=60, job_lease_seconds=60)
    production = Settings(
        demo_mode=False,
        auto_create_schema=False,
        session_secret="secure-session-secret",
        csrf_secret="secure-csrf-secret",
        pseudonymization_key="secure-pseudonym-key",
        s3_secret_key="secure-object-secret",
    )
    assert not production.demo_mode
    get_settings.cache_clear()
    assert get_settings().demo_mode
    get_settings.cache_clear()

    assert normalize_filename(r"C:\unsafe path\scan name.pdf") == "scan-name.pdf"
    with pytest.raises(DomainError, match="empty or unsafe"):
        normalize_filename("...")
    with pytest.raises(DomainError, match="empty"):
        validate_upload(b"", filename="a.pdf", media_type="application/pdf", maximum_bytes=10)
    with pytest.raises(DomainError, match="size limit"):
        validate_upload(b"123", filename="a.pdf", media_type="application/pdf", maximum_bytes=2)
    assert (
        validate_upload(
            b"%PDF-1.7\n",
            filename=str(tmp_path / "a.pdf"),
            media_type="application/pdf",
            maximum_bytes=20,
        )
        == "a.pdf"
    )

    key = b"k" * 32
    first = pseudonymize(" patient-1 ", key=key, namespace="patient")
    assert first == pseudonymize("patient-1", key=key, namespace="patient")
    assert first != pseudonymize("patient-1", key=key, namespace="encounter")
    with pytest.raises(ValueError, match="32 bytes"):
        pseudonymize("patient", key=b"short", namespace="patient")
    with pytest.raises(ValueError, match="empty identifier"):
        pseudonymize(" ", key=key, namespace="patient")

    not_found = NotFoundError("Form", "f-1")
    assert not_found.status_code == 404 and "f-1" in str(not_found)
    conflict = ConflictError("DUPLICATE", "Already exists")
    assert conflict.status_code == 409 and conflict.code == "DUPLICATE"


def test_coverage_document_and_tabular_remaining_paths(
    allergy_form: FormDefinition,
    evidence: EvidenceReference,
    fixed_time: datetime,
) -> None:
    with pytest.raises(ValidationError, match="Positive events"):
        CoverageInputs(recorded_responses=2, usable_responses=1, positive_events=2)
    with pytest.raises(ValidationError, match="eligible opportunities"):
        CoverageInputs(
            eligible_opportunities=1,
            recorded_responses=2,
            usable_responses=1,
            positive_events=0,
        )
    metric = calculate_coverage(
        CoverageInputs(
            eligible_opportunities=0,
            recorded_responses=0,
            usable_responses=0,
            positive_events=0,
        )
    )
    assert metric.completion is None and metric.prevalence is None

    native_evidence = evidence.model_copy(
        update={"extraction_method": ExtractionMethod.NATIVE_TEXT, "confidence": None}
    )
    unknown = extract_allergy_candidate("Rubrique sans information", evidence=native_evidence)
    assert unknown.assertion == AnswerState.UNKNOWN and unknown.confidence == 0
    certain = extract_allergy_candidate(
        "Allergie avec anaphylaxie à l'amoxicilline", evidence=native_evidence
    )
    assert certain.confidence == 1.0 and certain.reaction == "Anaphylaxis"

    answers = (
        TabularAnswer(
            response_id="r1",
            patient_pseudonym="p1",
            item_path="Q1",
            raw_value="Oui",
            authored_at=fixed_time,
            group_instance="g1",
            unit="kg",
        ),
        TabularAnswer(
            response_id="r2",
            patient_pseudonym="p2",
            item_path="Q1",
            raw_value=None,
            authored_at=fixed_time,
            lifecycle_status=LifecycleStatus.DELETED,
        ),
    )
    events = TabularFormAdapter().canonicalize(
        allergy_form, answers, establishment_id="site-a", evidence=evidence
    )
    assert events[0].value == "Oui" and events[0].group_instance == "g1"
    assert events[1].state == AnswerState.DELETED and events[1].value is None
