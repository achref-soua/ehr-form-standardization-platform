"""Schema-declared JSON and XML adapters for bounded structured form exports."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Self, cast
from xml.etree.ElementTree import Element

from defusedxml import ElementTree
from pydantic import Field, ValidationError, model_validator

from ehrfs.canonical.conditions import conditions_satisfied
from ehrfs.canonical.state import derive_answer_state
from ehrfs.domain.enums import AnswerState, ExtractionMethod, LifecycleStatus
from ehrfs.domain.errors import DomainError
from ehrfs.domain.identity import deterministic_uuid, sha256_hex
from ehrfs.domain.models import (
    CanonicalAnswerEvent,
    DisplayCondition,
    DomainModel,
    EvidenceReference,
    FormDefinition,
    ItemDefinition,
    LifecycleEvent,
    ScalarValue,
    ValueOption,
)
from ehrfs.fingerprinting.service import fingerprint_form

SCHEMA_VERSION = "ehrfs-structured/1.0"
DataType = Literal[
    "boolean", "integer", "decimal", "string", "text", "date", "datetime", "coding", "group"
]


class StructuredAnswerPayload(DomainModel):
    item_path: str
    value: Any | None = None
    unit: str | None = None
    group_instance: str | None = None
    enabled: bool | None = None


class StructuredResponsePayload(DomainModel):
    schema_version: Literal["ehrfs-structured/1.0"]
    response_id: str
    authored_at: datetime
    lifecycle_status: LifecycleStatus = LifecycleStatus.SIGNED
    source_sequence: int = Field(default=0, ge=0)
    supersedes_response_id: str | None = None
    answers: tuple[StructuredAnswerPayload, ...]

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        if self.authored_at.utcoffset() is None:
            msg = "authored_at must include a timezone"
            raise ValueError(msg)
        requires_prior = self.lifecycle_status in {
            LifecycleStatus.CORRECTED,
            LifecycleStatus.VOIDED,
        }
        if requires_prior and not self.supersedes_response_id:
            msg = f"{self.lifecycle_status} requires supersedes_response_id"
            raise ValueError(msg)
        return self


def _load_json_object(payload: bytes) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise DomainError("INVALID_STRUCTURED_JSON", "Payload is not valid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise DomainError("INVALID_STRUCTURED_JSON", "Payload must be a JSON object")
    return value


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise DomainError("INVALID_STRUCTURED_VALUE", "Datetime value is invalid") from error
    if parsed.utcoffset() is None:
        raise DomainError("INVALID_STRUCTURED_VALUE", "Datetime value requires a timezone")
    return parsed


def _boolean_value(value: Any) -> ScalarValue:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.casefold() in {"true", "false"}:
        return value.casefold() == "true"
    raise ValueError


def _integer_value(value: Any) -> ScalarValue:
    if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
        raise ValueError
    return int(value)


def _decimal_value(value: Any) -> ScalarValue:
    if isinstance(value, bool):
        raise TypeError
    converted = Decimal(str(value))
    if not converted.is_finite():
        raise ValueError
    return converted


def _text_value(value: Any) -> ScalarValue:
    if not isinstance(value, str):
        raise TypeError
    return value


def _date_value(value: Any) -> ScalarValue:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError


def _datetime_value(value: Any) -> ScalarValue:
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValueError
        return value
    if isinstance(value, str):
        return _parse_datetime(value)
    raise ValueError


VALUE_COERCERS: dict[str, Callable[[Any], ScalarValue]] = {
    "boolean": _boolean_value,
    "integer": _integer_value,
    "decimal": _decimal_value,
    "string": _text_value,
    "text": _text_value,
    "coding": _text_value,
    "date": _date_value,
    "datetime": _datetime_value,
}


def _coerce_value(value: Any, data_type: DataType) -> ScalarValue | None:
    if value is None:
        return None
    converter = VALUE_COERCERS.get(data_type)
    if converter is None:
        raise DomainError("INVALID_STRUCTURED_VALUE", "Group items cannot carry values")
    try:
        return converter(value)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise DomainError(
            "INVALID_STRUCTURED_VALUE",
            f"Value {value!r} does not match declared type {data_type}",
        ) from error


def _flatten_items(
    items: tuple[ItemDefinition, ...],
    *,
    repeated_root: str | None = None,
) -> dict[str, tuple[ItemDefinition, str | None]]:
    result: dict[str, tuple[ItemDefinition, str | None]] = {}
    for item in items:
        local_root = item.path if item.repeats else repeated_root
        result[item.path] = (item, local_root)
        result.update(_flatten_items(item.children, repeated_root=local_root))
    return result


def _validate_answer_shape(
    response: StructuredResponsePayload,
    definitions: dict[str, tuple[ItemDefinition, str | None]],
) -> dict[tuple[str, str | None], StructuredAnswerPayload]:
    indexed: dict[tuple[str, str | None], StructuredAnswerPayload] = {}
    for answer in response.answers:
        item_record = definitions.get(answer.item_path)
        if item_record is None:
            raise DomainError("UNKNOWN_ITEM_PATH", f"Unknown answer path {answer.item_path}")
        item, repeated_root = item_record
        if item.data_type == "group":
            raise DomainError("INVALID_STRUCTURED_VALUE", "Group items cannot carry answers")
        if repeated_root is not None and not answer.group_instance:
            raise DomainError(
                "REPEATED_GROUP_CONFLICT",
                f"Repeated answer {answer.item_path} requires group_instance",
            )
        if repeated_root is None and answer.group_instance is not None:
            raise DomainError(
                "REPEATED_GROUP_CONFLICT",
                f"Non-repeated answer {answer.item_path} cannot use group_instance",
            )
        key = (answer.item_path, answer.group_instance)
        if key in indexed:
            raise DomainError("DUPLICATE_ANSWER", "Response repeats one item/group identity")
        indexed[key] = answer
    return indexed


def _expected_answer_keys(
    definitions: dict[str, tuple[ItemDefinition, str | None]],
    indexed: dict[tuple[str, str | None], StructuredAnswerPayload],
) -> tuple[tuple[str, str | None], ...]:
    instances: dict[str, set[str]] = {}
    for path, group_instance in indexed:
        repeated_root = definitions[path][1]
        if repeated_root is not None and group_instance is not None:
            instances.setdefault(repeated_root, set()).add(group_instance)
    expected: set[tuple[str, str | None]] = set(indexed)
    for path, (item, repeated_root) in definitions.items():
        if item.data_type == "group":
            continue
        if repeated_root is None:
            expected.add((path, None))
        else:
            expected.update((path, instance) for instance in instances.get(repeated_root, set()))
    return tuple(sorted(expected, key=lambda value: (value[1] or "", value[0])))


def _lifecycle_event(
    response: StructuredResponsePayload,
    *,
    establishment_id: str,
    item_path: str,
    group_instance: str | None,
) -> LifecycleEvent:
    supersedes = None
    if response.supersedes_response_id is not None:
        supersedes = deterministic_uuid(
            "canonical-answer",
            establishment_id,
            response.supersedes_response_id,
            item_path,
            group_instance or "0",
        )
    return LifecycleEvent(
        status=response.lifecycle_status,
        occurred_at=response.authored_at,
        source_sequence=response.source_sequence,
        supersedes_event_id=supersedes,
    )


def _canonicalize(
    definition: FormDefinition,
    response: StructuredResponsePayload,
    *,
    establishment_id: str,
    patient_pseudonym: str,
    evidence_object_key: str,
    payload_checksum: str,
    media_type: str,
    locators: dict[tuple[str, str | None], str],
) -> tuple[CanonicalAnswerEvent, ...]:
    definitions = _flatten_items(definition.items)
    indexed = _validate_answer_shape(response, definitions)
    fingerprints = fingerprint_form(definition)
    events: list[CanonicalAnswerEvent] = []
    for item_path, group_instance in _expected_answer_keys(definitions, indexed):
        item = definitions[item_path][0]
        answer = indexed.get((item_path, group_instance))
        raw_value = answer.value if answer is not None else None
        typed_value = _coerce_value(raw_value, item.data_type)
        answers_by_path: dict[str, ScalarValue | None] = {}
        for (candidate_path, candidate_group), candidate in indexed.items():
            if candidate_group in {None, group_instance}:
                candidate_item = definitions[candidate_path][0]
                answers_by_path.setdefault(
                    candidate_path,
                    _coerce_value(candidate.value, candidate_item.data_type),
                )
        enabled = conditions_satisfied(item.display_conditions, answers_by_path)
        if answer is not None and answer.enabled is not None and answer.enabled != enabled:
            raise DomainError(
                "CONDITIONAL_LOGIC_CONFLICT",
                f"Source display state contradicts definition for {item_path}",
            )
        state = derive_answer_state(
            response_present=answer is not None,
            enabled=enabled,
            raw_value=typed_value,
            lifecycle_status=response.lifecycle_status,
        )
        locator = locators.get((item_path, group_instance), "/answers")
        evidence = EvidenceReference(
            object_key=evidence_object_key,
            checksum_sha256=payload_checksum,
            media_type=media_type,
            json_pointer=locator if media_type == "application/json" else None,
            source_locator=locator,
            extraction_method=ExtractionMethod.STRUCTURED_FORM,
            extractor_version=SCHEMA_VERSION,
        )
        events.append(
            CanonicalAnswerEvent(
                event_id=deterministic_uuid(
                    "canonical-answer",
                    establishment_id,
                    response.response_id,
                    item_path,
                    group_instance or "0",
                ),
                establishment_id=establishment_id,
                patient_pseudonym=patient_pseudonym,
                form_id=definition.form_id,
                form_version=definition.version,
                source_fingerprint=fingerprints.source,
                compatibility_fingerprint=fingerprints.compatibility,
                item_path=item_path,
                group_instance=group_instance,
                state=state,
                value=typed_value if state == AnswerState.PRESENT else None,
                raw_value=raw_value,
                unit=answer.unit if answer is not None else item.unit,
                authored_at=response.authored_at,
                lifecycle=(
                    _lifecycle_event(
                        response,
                        establishment_id=establishment_id,
                        item_path=item_path,
                        group_instance=group_instance,
                    ),
                ),
                evidence=(evidence,),
            )
        )
    return tuple(events)


class JsonFormAdapter:
    connector_version = "structured-json/1.0.0"

    def parse_definition(self, payload: bytes) -> FormDefinition:
        data = _load_json_object(payload)
        if data.get("schema_version") != SCHEMA_VERSION or "form" not in data:
            raise DomainError(
                "UNSUPPORTED_STRUCTURED_SCHEMA",
                f"JSON definition must declare {SCHEMA_VERSION}",
            )
        try:
            return FormDefinition.model_validate(data["form"])
        except ValidationError as error:
            raise DomainError(
                "INVALID_FORM_DEFINITION", "JSON form definition is invalid"
            ) from error

    def parse_response(
        self,
        definition: FormDefinition,
        payload: bytes,
        *,
        establishment_id: str,
        patient_pseudonym: str,
        evidence_object_key: str,
    ) -> tuple[CanonicalAnswerEvent, ...]:
        data = _load_json_object(payload)
        try:
            response = StructuredResponsePayload.model_validate(data)
        except ValidationError as error:
            raise DomainError("INVALID_STRUCTURED_RESPONSE", "JSON response is invalid") from error
        locators = {
            (answer.item_path, answer.group_instance): f"/answers/{index}"
            for index, answer in enumerate(response.answers)
        }
        return _canonicalize(
            definition,
            response,
            establishment_id=establishment_id,
            patient_pseudonym=patient_pseudonym,
            evidence_object_key=evidence_object_key,
            payload_checksum=sha256_hex(payload),
            media_type="application/json",
            locators=locators,
        )


def _required_attribute(element: Element, name: str) -> str:
    value = element.get(name)
    if value is None or not value.strip():
        raise DomainError("INVALID_STRUCTURED_XML", f"XML element requires {name}")
    return str(value)


def _xml_boolean(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    if value not in {"true", "false"}:
        raise DomainError("INVALID_STRUCTURED_XML", f"Invalid XML boolean {value!r}")
    return value == "true"


def _xml_item(element: Element, *, parent_path: str, order: int) -> ItemDefinition:
    item_id = _required_attribute(element, "id")
    path = element.get("path") or (f"{parent_path}/{item_id}" if parent_path else item_id)
    data_type = _required_attribute(element, "data-type")
    if data_type not in {
        "boolean",
        "integer",
        "decimal",
        "string",
        "text",
        "date",
        "datetime",
        "coding",
        "group",
    }:
        raise DomainError("INVALID_STRUCTURED_XML", f"Unsupported item type {data_type}")
    options = tuple(
        ValueOption(
            code=_required_attribute(option, "code"),
            display=option.get("display") or _required_attribute(option, "code"),
            system=option.get("system"),
        )
        for option in element.findall("option")
    )
    conditions: list[DisplayCondition] = []
    for condition in element.findall("condition"):
        raw_expected = _required_attribute(condition, "expected-json")
        try:
            expected = json.loads(raw_expected)
        except json.JSONDecodeError as error:
            raise DomainError("INVALID_STRUCTURED_XML", "Condition value is not JSON") from error
        conditions.append(
            DisplayCondition(
                source_item_path=_required_attribute(condition, "source-path"),
                operator=cast(Any, _required_attribute(condition, "operator")),
                expected=expected,
            )
        )
    children = tuple(
        _xml_item(child, parent_path=path, order=child_order)
        for child_order, child in enumerate(element.findall("item"))
    )
    try:
        return ItemDefinition(
            item_id=item_id,
            path=path,
            label=element.get("label") or item_id,
            data_type=cast(DataType, data_type),
            order=int(element.get("order", order)),
            order_semantic=_xml_boolean(element.get("order-semantic"), default=True),
            required=_xml_boolean(element.get("required")),
            repeats=_xml_boolean(element.get("repeats")),
            unit=element.get("unit"),
            value_options=options,
            display_conditions=tuple(conditions),
            children=children,
            calculation=element.get("calculation"),
        )
    except (ValidationError, ValueError) as error:
        raise DomainError("INVALID_STRUCTURED_XML", "XML item definition is invalid") from error


class XmlFormAdapter:
    connector_version = "structured-xml/1.0.0"

    def _root(self, payload: bytes, expected_tag: str) -> Element:
        try:
            root = ElementTree.fromstring(payload)
        except (ElementTree.ParseError, ValueError) as error:
            raise DomainError(
                "INVALID_STRUCTURED_XML", "XML payload is malformed or unsafe"
            ) from error
        if root.tag != expected_tag or root.get("schema-version") != SCHEMA_VERSION:
            raise DomainError(
                "UNSUPPORTED_STRUCTURED_SCHEMA",
                f"XML payload must be {expected_tag} at {SCHEMA_VERSION}",
            )
        return root

    def parse_definition(self, payload: bytes) -> FormDefinition:
        root = self._root(payload, "ehrfs-form-definition")
        items = tuple(
            _xml_item(item, parent_path="", order=order)
            for order, item in enumerate(root.findall("item"))
        )
        metadata = {
            _required_attribute(element, "key"): _required_attribute(element, "value")
            for element in root.findall("metadata")
        }
        try:
            return FormDefinition(
                ehr_product=_required_attribute(root, "ehr-product"),
                ehr_version=_required_attribute(root, "ehr-version"),
                form_id=_required_attribute(root, "form-id"),
                form_family=_required_attribute(root, "form-family"),
                version=_required_attribute(root, "version"),
                title=_required_attribute(root, "title"),
                items=items,
                source_order_semantic=_xml_boolean(root.get("source-order-semantic"), default=True),
                metadata=metadata,
            )
        except ValidationError as error:
            raise DomainError(
                "INVALID_FORM_DEFINITION", "XML form definition is invalid"
            ) from error

    def parse_response(
        self,
        definition: FormDefinition,
        payload: bytes,
        *,
        establishment_id: str,
        patient_pseudonym: str,
        evidence_object_key: str,
    ) -> tuple[CanonicalAnswerEvent, ...]:
        root = self._root(payload, "ehrfs-form-response")
        answers: list[StructuredAnswerPayload] = []
        locators: dict[tuple[str, str | None], str] = {}
        for index, element in enumerate(root.findall("answer"), start=1):
            item_path = _required_attribute(element, "item-path")
            group_instance = element.get("group-instance")
            value_element = element.find("value")
            answer = StructuredAnswerPayload(
                item_path=item_path,
                value=value_element.text if value_element is not None else None,
                unit=element.get("unit"),
                group_instance=group_instance,
                enabled=(
                    _xml_boolean(element.get("enabled"))
                    if element.get("enabled") is not None
                    else None
                ),
            )
            answers.append(answer)
            locators[(item_path, group_instance)] = f"/ehrfs-form-response/answer[{index}]"
        try:
            response = StructuredResponsePayload(
                schema_version=SCHEMA_VERSION,
                response_id=_required_attribute(root, "response-id"),
                authored_at=_parse_datetime(_required_attribute(root, "authored-at")),
                lifecycle_status=LifecycleStatus(root.get("lifecycle-status", "SIGNED")),
                source_sequence=int(root.get("source-sequence", "0")),
                supersedes_response_id=root.get("supersedes-response-id"),
                answers=tuple(answers),
            )
        except (ValidationError, ValueError) as error:
            raise DomainError("INVALID_STRUCTURED_RESPONSE", "XML response is invalid") from error
        return _canonicalize(
            definition,
            response,
            establishment_id=establishment_id,
            patient_pseudonym=patient_pseudonym,
            evidence_object_key=evidence_object_key,
            payload_checksum=sha256_hex(payload),
            media_type="application/xml",
            locators=locators,
        )


__all__ = ["JsonFormAdapter", "StructuredResponsePayload", "XmlFormAdapter"]
