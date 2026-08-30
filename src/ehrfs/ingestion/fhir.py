"""Bounded FHIR R4 Questionnaire and QuestionnaireResponse adapter.

The adapter implements the subset used by the demonstration and rejects unsupported
extensions. It is not presented as a complete FHIR validator.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, cast

from pydantic import TypeAdapter, ValidationError

from ehrfs.canonical.conditions import conditions_satisfied
from ehrfs.canonical.state import derive_answer_state
from ehrfs.domain.enums import AnswerState, ExtractionMethod, LifecycleStatus
from ehrfs.domain.errors import DomainError
from ehrfs.domain.identity import deterministic_uuid, sha256_hex
from ehrfs.domain.models import (
    CanonicalAnswerEvent,
    DisplayCondition,
    EvidenceReference,
    FormDefinition,
    ItemDefinition,
    ScalarValue,
    ValueOption,
)
from ehrfs.fingerprinting.service import fingerprint_form

JSON_OBJECT = TypeAdapter(dict[str, Any])
TYPE_MAP = {
    "boolean": "boolean",
    "decimal": "decimal",
    "integer": "integer",
    "date": "date",
    "dateTime": "datetime",
    "string": "string",
    "text": "text",
    "choice": "coding",
    "open-choice": "coding",
    "group": "group",
}
ItemDataType = Literal[
    "boolean", "integer", "decimal", "string", "text", "date", "datetime", "coding", "group"
]
ConditionOperator = Literal["eq", "ne", "gt", "gte", "lt", "lte", "exists"]


def _load_json(payload: bytes, expected_resource: str) -> dict[str, Any]:
    try:
        data = JSON_OBJECT.validate_python(json.loads(payload))
    except (json.JSONDecodeError, ValidationError) as error:
        raise DomainError("INVALID_FHIR_JSON", "FHIR payload is not a JSON object") from error
    if data.get("resourceType") != expected_resource:
        raise DomainError(
            "INVALID_FHIR_RESOURCE",
            f"Expected {expected_resource}; received {data.get('resourceType')!r}",
        )
    return data


def _parse_answer_option(option: dict[str, Any]) -> ValueOption:
    coding = option.get("valueCoding")
    if isinstance(coding, dict):
        code = coding.get("code")
        if not isinstance(code, str):
            raise DomainError("INVALID_FHIR_OPTION", "Coding options require a string code")
        return ValueOption(
            code=code,
            display=str(coding.get("display", code)),
            system=str(coding["system"]) if "system" in coding else None,
        )
    for key in ("valueString", "valueInteger"):
        if key in option:
            value = str(option[key])
            return ValueOption(code=value, display=value)
    raise DomainError("UNSUPPORTED_FHIR_OPTION", "Unsupported Questionnaire answerOption")


def _parse_condition(value: dict[str, Any], path_by_link_id: dict[str, str]) -> DisplayCondition:
    question = value.get("question")
    if not isinstance(question, str) or question not in path_by_link_id:
        raise DomainError("INVALID_FHIR_CONDITION", "enableWhen references an unknown question")
    operator = value.get("operator", "=")
    operator_map: dict[str, ConditionOperator] = {
        "=": "eq",
        "!=": "ne",
        ">": "gt",
        ">=": "gte",
        "<": "lt",
        "<=": "lte",
        "exists": "exists",
    }
    if operator not in operator_map:
        raise DomainError(
            "UNSUPPORTED_FHIR_CONDITION",
            f"Unsupported enableWhen operator {operator}",
        )
    answer_keys = [key for key in value if key.startswith("answer")]
    if len(answer_keys) != 1:
        raise DomainError("INVALID_FHIR_CONDITION", "enableWhen requires exactly one answer value")
    expected_raw = value[answer_keys[0]]
    if isinstance(expected_raw, dict) and "code" in expected_raw:
        expected_raw = expected_raw["code"]
    return DisplayCondition(
        source_item_path=path_by_link_id[question],
        operator=operator_map[operator],
        expected=expected_raw,
    )


def _build_items(
    raw_items: list[dict[str, Any]],
    *,
    parent_path: str,
    path_by_link_id: dict[str, str],
) -> tuple[ItemDefinition, ...]:
    for raw in raw_items:
        link_id = raw.get("linkId")
        if not isinstance(link_id, str):
            raise DomainError("INVALID_FHIR_ITEM", "Questionnaire items require linkId")
        path_by_link_id[link_id] = f"{parent_path}/{link_id}" if parent_path else link_id

    result: list[ItemDefinition] = []
    for order, raw in enumerate(raw_items):
        if raw.get("extension"):
            raise DomainError(
                "UNSUPPORTED_FHIR_EXTENSION",
                "Questionnaire item extensions require an explicit adapter profile",
            )
        link_id = str(raw["linkId"])
        raw_type = raw.get("type")
        if raw_type not in TYPE_MAP:
            raise DomainError("UNSUPPORTED_FHIR_ITEM_TYPE", f"Unsupported item type {raw_type!r}")
        raw_children = raw.get("item", [])
        if not isinstance(raw_children, list):
            raise DomainError("INVALID_FHIR_ITEM", "Nested Questionnaire items must be a list")
        conditions_raw = raw.get("enableWhen", [])
        if not isinstance(conditions_raw, list):
            raise DomainError("INVALID_FHIR_CONDITION", "enableWhen must be a list")
        conditions = tuple(
            _parse_condition(condition, path_by_link_id) for condition in conditions_raw
        )
        options_raw = raw.get("answerOption", [])
        if not isinstance(options_raw, list):
            raise DomainError("INVALID_FHIR_OPTION", "answerOption must be a list")
        path = path_by_link_id[link_id]
        result.append(
            ItemDefinition(
                item_id=link_id,
                path=path,
                label=str(raw.get("text", link_id)),
                data_type=cast(ItemDataType, TYPE_MAP[raw_type]),
                order=order,
                order_semantic=True,
                required=bool(raw.get("required", False)),
                repeats=bool(raw.get("repeats", False)),
                value_options=tuple(_parse_answer_option(option) for option in options_raw),
                display_conditions=conditions,
                children=_build_items(
                    raw_children,
                    parent_path=path,
                    path_by_link_id=path_by_link_id,
                ),
            )
        )
    return tuple(result)


def _extract_answer(answer: dict[str, Any]) -> ScalarValue | None:
    keys = [key for key in answer if key.startswith("value")]
    if len(keys) != 1:
        raise DomainError("INVALID_FHIR_ANSWER", "Answers require exactly one value[x]")
    raw = answer[keys[0]]
    if isinstance(raw, dict):
        if "code" in raw:
            return str(raw["code"])
        if "value" in raw:
            nested_value = raw["value"]
            if isinstance(nested_value, (str, int, float, bool)):
                return nested_value
        raise DomainError("UNSUPPORTED_FHIR_ANSWER", "Unsupported complex FHIR answer")
    if not isinstance(raw, (str, int, float, bool)):
        raise DomainError("UNSUPPORTED_FHIR_ANSWER", "Unsupported FHIR answer value")
    return raw


def _flatten_definition(items: tuple[ItemDefinition, ...]) -> dict[str, ItemDefinition]:
    result: dict[str, ItemDefinition] = {}
    for item in items:
        result[item.path] = item
        result.update(_flatten_definition(item.children))
    return result


@dataclass(frozen=True, slots=True)
class _ResponseItem:
    path: str
    response_present: bool
    value: ScalarValue | None
    group_instance: str | None
    json_pointer: str


def _repeated_paths(items: tuple[ItemDefinition, ...]) -> frozenset[str]:
    paths: set[str] = set()
    for item in items:
        if item.repeats:
            paths.add(item.path)
        paths.update(_repeated_paths(item.children))
    return frozenset(paths)


def _flatten_response(
    items: list[dict[str, Any]],
    *,
    parent_path: str = "",
    parent_pointer: str = "/item",
    parent_group_instance: str | None = None,
    repeated_paths: frozenset[str],
) -> tuple[_ResponseItem, ...]:
    result: list[_ResponseItem] = []
    occurrence_by_path: dict[str, int] = {}
    for item_index, item in enumerate(items):
        link_id = item.get("linkId")
        if not isinstance(link_id, str):
            raise DomainError("INVALID_FHIR_RESPONSE", "Response items require linkId")
        path = f"{parent_path}/{link_id}" if parent_path else link_id
        occurrence = occurrence_by_path.get(path, 0)
        occurrence_by_path[path] = occurrence + 1
        group_instance = parent_group_instance
        if path in repeated_paths:
            local_instance = f"{path}:{occurrence}"
            group_instance = (
                f"{parent_group_instance}/{local_instance}"
                if parent_group_instance
                else local_instance
            )
        answers = item.get("answer", [])
        if not isinstance(answers, list):
            raise DomainError("INVALID_FHIR_RESPONSE", "Response answers must be a list")
        nested = item.get("item", [])
        if not isinstance(nested, list):
            raise DomainError("INVALID_FHIR_RESPONSE", "Nested response items must be a list")
        item_pointer = f"{parent_pointer}/{item_index}"
        if nested:
            result.extend(
                _flatten_response(
                    nested,
                    parent_path=path,
                    parent_pointer=f"{item_pointer}/item",
                    parent_group_instance=group_instance,
                    repeated_paths=repeated_paths,
                )
            )
        elif answers:
            for answer_index, answer in enumerate(answers):
                answer_group = group_instance
                if len(answers) > 1:
                    suffix = f"answer:{answer_index}"
                    answer_group = f"{group_instance}/{suffix}" if group_instance else suffix
                result.append(
                    _ResponseItem(
                        path=path,
                        response_present=True,
                        value=_extract_answer(answer),
                        group_instance=answer_group,
                        json_pointer=f"{item_pointer}/answer/{answer_index}",
                    )
                )
        else:
            result.append(
                _ResponseItem(
                    path=path,
                    response_present=False,
                    value=None,
                    group_instance=group_instance,
                    json_pointer=item_pointer,
                )
            )
    return tuple(result)


class FhirR4Adapter:
    connector_version = "fhir-r4/1.0.0"

    def parse_definition(self, payload: bytes) -> FormDefinition:
        data = _load_json(payload, "Questionnaire")
        raw_items = data.get("item", [])
        if not isinstance(raw_items, list):
            raise DomainError("INVALID_FHIR_QUESTIONNAIRE", "Questionnaire.item must be a list")
        path_by_link_id: dict[str, str] = {}
        items = _build_items(raw_items, parent_path="", path_by_link_id=path_by_link_id)
        identifier = str(data.get("url") or data.get("id") or "unknown-questionnaire")
        return FormDefinition(
            ehr_product="FHIR R4",
            ehr_version="4.0.1",
            form_id=identifier,
            form_family=identifier,
            version=str(data.get("version", "unversioned")),
            title=str(data.get("title") or data.get("name") or identifier),
            items=items,
            source_order_semantic=True,
            metadata={"status": str(data.get("status", "unknown"))},
        )

    def parse_response(
        self,
        definition: FormDefinition,
        payload: bytes,
        *,
        establishment_id: str,
        patient_pseudonym: str,
        evidence_object_key: str,
    ) -> tuple[CanonicalAnswerEvent, ...]:
        data = _load_json(payload, "QuestionnaireResponse")
        raw_items = data.get("item", [])
        if not isinstance(raw_items, list):
            raise DomainError("INVALID_FHIR_RESPONSE", "QuestionnaireResponse.item must be a list")
        item_definitions = _flatten_definition(definition.items)
        response_items = _flatten_response(
            raw_items,
            repeated_paths=_repeated_paths(definition.items),
        )
        response_by_path: dict[str, list[_ResponseItem]] = {}
        for response_item in response_items:
            response_by_path.setdefault(response_item.path, []).append(response_item)
        fingerprints = fingerprint_form(definition)
        response_id = str(data.get("id", sha256_hex(payload)))
        authored_at = datetime.fromisoformat(
            str(data.get("authored", "1970-01-01T00:00:00+00:00")).replace("Z", "+00:00")
        )
        checksum = sha256_hex(payload)
        events: list[CanonicalAnswerEvent] = []
        for path, definition_item in item_definitions.items():
            if definition_item.data_type == "group":
                continue
            matching_items = response_by_path.get(
                path,
                [
                    _ResponseItem(
                        path=path,
                        response_present=False,
                        value=None,
                        group_instance=None,
                        json_pointer="/item",
                    )
                ],
            )
            for response_item in matching_items:
                answers_by_path: dict[str, ScalarValue | None] = {}
                for candidate in response_items:
                    same_group = candidate.group_instance == response_item.group_instance
                    global_context = candidate.group_instance is None
                    if (same_group or global_context) and candidate.path not in answers_by_path:
                        answers_by_path[candidate.path] = candidate.value
                enabled = conditions_satisfied(
                    definition_item.display_conditions,
                    answers_by_path,
                )
                state = derive_answer_state(
                    response_present=response_item.response_present,
                    enabled=enabled,
                    raw_value=response_item.value,
                    lifecycle_status=LifecycleStatus.SIGNED,
                )
                events.append(
                    CanonicalAnswerEvent(
                        event_id=deterministic_uuid(
                            "canonical-answer",
                            establishment_id,
                            response_id,
                            path,
                            response_item.group_instance or "0",
                        ),
                        establishment_id=establishment_id,
                        patient_pseudonym=patient_pseudonym,
                        form_id=definition.form_id,
                        form_version=definition.version,
                        source_fingerprint=fingerprints.source,
                        compatibility_fingerprint=fingerprints.compatibility,
                        item_path=path,
                        group_instance=response_item.group_instance,
                        state=state,
                        value=response_item.value if state == AnswerState.PRESENT else None,
                        raw_value=response_item.value,
                        unit=definition_item.unit,
                        authored_at=authored_at,
                        evidence=(
                            EvidenceReference(
                                object_key=evidence_object_key,
                                checksum_sha256=checksum,
                                media_type="application/fhir+json",
                                json_pointer=response_item.json_pointer,
                                extraction_method=ExtractionMethod.FHIR,
                                extractor_version=self.connector_version,
                            ),
                        ),
                    )
                )
        return tuple(events)
