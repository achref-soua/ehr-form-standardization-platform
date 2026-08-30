from __future__ import annotations

import json

import pytest

from ehrfs.demo import allergy_form, blood_pressure_form
from ehrfs.domain.enums import AnswerState
from ehrfs.domain.errors import DomainError
from ehrfs.ingestion.fhir import FhirR4Adapter


def _payload(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode()


def test_hidden_conditional_item_is_not_recorded_as_null() -> None:
    response = {
        "resourceType": "QuestionnaireResponse",
        "id": "allergy-1",
        "authored": "2026-08-12T09:30:00Z",
        "item": [{"linkId": "Q1", "answer": [{"valueCoding": {"code": "Non"}}]}],
    }

    events = FhirR4Adapter().parse_response(
        allergy_form(),
        _payload(response),
        establishment_id="site-a",
        patient_pseudonym="p-demo",
        evidence_object_key="raw/response.json",
    )

    by_path = {event.item_path: event for event in events}
    assert by_path["Q1"].state == AnswerState.EXPLICITLY_ABSENT
    assert by_path["Q2"].state == AnswerState.NOT_DISPLAYED_BY_FORM_LOGIC
    assert by_path["Q2"].value is None


def test_repeated_blood_pressure_children_keep_paired_group_identity() -> None:
    response = {
        "resourceType": "QuestionnaireResponse",
        "id": "bp-1",
        "authored": "2026-08-12T09:30:00Z",
        "item": [
            {
                "linkId": "BP",
                "item": [
                    {"linkId": "SYS", "answer": [{"valueDecimal": 121}]},
                    {"linkId": "DIA", "answer": [{"valueDecimal": 79}]},
                    {"linkId": "POSITION", "answer": [{"valueString": "assis"}]},
                ],
            },
            {
                "linkId": "BP",
                "item": [
                    {"linkId": "SYS", "answer": [{"valueDecimal": 118}]},
                    {"linkId": "DIA", "answer": [{"valueDecimal": 76}]},
                    {"linkId": "POSITION", "answer": [{"valueString": "debout"}]},
                ],
            },
        ],
    }

    events = FhirR4Adapter().parse_response(
        blood_pressure_form(),
        _payload(response),
        establishment_id="site-a",
        patient_pseudonym="p-demo",
        evidence_object_key="raw/bp.json",
    )

    assert len(events) == 6
    groups = {event.group_instance for event in events}
    assert groups == {"BP:0", "BP:1"}
    first = {event.item_path: event.value for event in events if event.group_instance == "BP:0"}
    second = {event.item_path: event.value for event in events if event.group_instance == "BP:1"}
    assert first == {"BP/SYS": 121, "BP/DIA": 79, "BP/POSITION": "assis"}
    assert second == {"BP/SYS": 118, "BP/DIA": 76, "BP/POSITION": "debout"}
    assert len({event.event_id for event in events}) == 6
    assert {event.evidence[0].json_pointer for event in events} == {
        "/item/0/item/0/answer/0",
        "/item/0/item/1/answer/0",
        "/item/0/item/2/answer/0",
        "/item/1/item/0/answer/0",
        "/item/1/item/1/answer/0",
        "/item/1/item/2/answer/0",
    }


def test_unsupported_fhir_extension_fails_explicitly() -> None:
    questionnaire = {
        "resourceType": "Questionnaire",
        "id": "custom",
        "status": "active",
        "item": [
            {
                "linkId": "Q1",
                "type": "string",
                "extension": [{"url": "https://example.invalid/private-semantics"}],
            }
        ],
    }

    with pytest.raises(DomainError, match="explicit adapter profile") as captured:
        FhirR4Adapter().parse_definition(_payload(questionnaire))

    assert captured.value.code == "UNSUPPORTED_FHIR_EXTENSION"
