from __future__ import annotations

import json
import stat
from datetime import UTC, date, datetime
from decimal import Decimal
from io import BytesIO
from uuid import UUID, uuid4
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest

from ehrfs.canonical.lifecycle import resolve_lifecycle
from ehrfs.demo import allergy_form, blood_pressure_form
from ehrfs.domain.enums import AnswerState, LifecycleStatus
from ehrfs.domain.errors import DomainError
from ehrfs.domain.models import (
    CanonicalAnswerEvent,
    FormDefinition,
    ItemDefinition,
    LifecycleEvent,
)
from ehrfs.ingestion.structured import DataType, JsonFormAdapter, XmlFormAdapter, _coerce_value
from ehrfs.security.archives import _validate_member, extract_safe_zip

SCHEMA_VERSION = "ehrfs-structured/1.0"


def _json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, default=str).encode()


def _definition_payload(definition: FormDefinition) -> bytes:
    return _json(
        {
            "schema_version": SCHEMA_VERSION,
            "form": definition.model_dump(mode="json"),
        }
    )


def _response(
    response_id: str,
    answers: list[dict[str, object]],
    **changes: object,
) -> bytes:
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "response_id": response_id,
        "authored_at": "2026-08-30T10:00:00Z",
        "lifecycle_status": "SIGNED",
        "answers": answers,
    }
    payload.update(changes)
    return _json(payload)


def _parse_json(definition: FormDefinition, payload: bytes) -> tuple[CanonicalAnswerEvent, ...]:
    return JsonFormAdapter().parse_response(
        definition,
        payload,
        establishment_id="site-a",
        patient_pseudonym="p-1",
        evidence_object_key="raw/response.json",
    )


def test_json_adapter_preserves_types_conditions_and_source_locators() -> None:
    adapter = JsonFormAdapter()
    definition = adapter.parse_definition(_definition_payload(allergy_form()))
    events = _parse_json(
        definition,
        _response(
            "allergy-json-1",
            [
                {"item_path": "Q1", "value": "Oui", "enabled": True},
                {"item_path": "Q2", "value": "Pénicilline", "enabled": True},
            ],
        ),
    )

    assert [event.state for event in events] == [AnswerState.PRESENT, AnswerState.PRESENT]
    assert events[1].value == "Pénicilline"
    assert events[1].evidence[0].json_pointer == "/answers/1"
    assert events[1].evidence[0].source_locator == "/answers/1"


def test_json_adapter_rejects_ambiguous_semantics_and_invalid_values() -> None:
    with pytest.raises(DomainError, match="declare"):
        JsonFormAdapter().parse_definition(_json({"form": {}}))
    with pytest.raises(DomainError, match="display state") as conflict:
        _parse_json(
            allergy_form(),
            _response(
                "conflict",
                [
                    {"item_path": "Q1", "value": "Non"},
                    {"item_path": "Q2", "value": "Latex", "enabled": True},
                ],
            ),
        )
    assert conflict.value.code == "CONDITIONAL_LOGIC_CONFLICT"
    with pytest.raises(DomainError, match="Unknown answer path"):
        _parse_json(allergy_form(), _response("unknown", [{"item_path": "Q99", "value": 1}]))
    with pytest.raises(DomainError, match="Group items"):
        _parse_json(
            blood_pressure_form(),
            _response("group-answer", [{"item_path": "BP", "value": "invalid"}]),
        )
    with pytest.raises(DomainError, match="cannot use group_instance"):
        _parse_json(
            allergy_form(),
            _response(
                "non-repeat-group",
                [{"item_path": "Q1", "value": "Oui", "group_instance": "g-1"}],
            ),
        )
    with pytest.raises(DomainError, match="repeats one item"):
        _parse_json(
            allergy_form(),
            _response(
                "duplicate",
                [
                    {"item_path": "Q1", "value": "Oui"},
                    {"item_path": "Q1", "value": "Non"},
                ],
            ),
        )
    with pytest.raises(DomainError, match="declared type decimal"):
        _parse_json(
            blood_pressure_form(),
            _response(
                "invalid-number",
                [
                    {
                        "item_path": "BP/SYS",
                        "value": "word",
                        "group_instance": "bp-1",
                    }
                ],
            ),
        )


def test_repeated_json_groups_emit_paired_missing_events() -> None:
    events = _parse_json(
        blood_pressure_form(),
        _response(
            "bp-json-1",
            [
                {"item_path": "BP/SYS", "value": 121, "group_instance": "bp-1"},
                {"item_path": "BP/POSITION", "value": "assis", "group_instance": "bp-1"},
                {"item_path": "BP/SYS", "value": 118, "group_instance": "bp-2"},
                {"item_path": "BP/DIA", "value": 76, "group_instance": "bp-2"},
                {"item_path": "BP/POSITION", "value": "debout", "group_instance": "bp-2"},
            ],
        ),
    )
    assert len(events) == 6
    missing = next(
        event for event in events if event.item_path == "BP/DIA" and event.group_instance == "bp-1"
    )
    assert missing.state == AnswerState.NOT_RECORDED
    with pytest.raises(DomainError, match="requires group_instance"):
        _parse_json(
            blood_pressure_form(),
            _response("bp-ambiguous", [{"item_path": "BP/SYS", "value": 121}]),
        )


def test_corrected_structured_response_supersedes_prior_weight() -> None:
    definition = FormDefinition(
        ehr_product="Bounded JSON",
        ehr_version="1",
        form_id="WEIGHT",
        form_family="WEIGHT",
        version="1",
        title="Weight",
        items=(
            ItemDefinition(
                item_id="WEIGHT",
                path="WEIGHT",
                label="Weight",
                data_type="decimal",
                order=0,
                unit="kg",
            ),
        ),
    )
    original = _parse_json(
        definition,
        _response("weight-1", [{"item_path": "WEIGHT", "value": 75, "unit": "kg"}]),
    )[0]
    corrected = _parse_json(
        definition,
        _response(
            "weight-2",
            [{"item_path": "WEIGHT", "value": 72.5, "unit": "kg"}],
            lifecycle_status="CORRECTED",
            supersedes_response_id="weight-1",
            source_sequence=2,
        ),
    )[0]

    resolved = resolve_lifecycle((original, corrected))
    assert resolved[0].state == AnswerState.SUPERSEDED and resolved[0].value is None
    assert resolved[1].state == AnswerState.PRESENT and resolved[1].value == 72.5
    assert corrected.lifecycle[0].supersedes_event_id == original.event_id


def test_xml_adapter_requires_safe_versioned_schema_and_preserves_xpath() -> None:
    definition_xml = f"""<ehrfs-form-definition schema-version="{SCHEMA_VERSION}"
      ehr-product="Bounded XML" ehr-version="1" form-id="vitals" form-family="vitals"
      version="1" title="Vitals">
      <metadata key="source" value="synthetic" />
      <item id="HEIGHT" data-type="decimal" label="Height" unit="cm" />
      <item id="CONSENT" data-type="boolean" label="Consent" />
    </ehrfs-form-definition>""".encode()
    adapter = XmlFormAdapter()
    definition = adapter.parse_definition(definition_xml)
    response_xml = f"""<ehrfs-form-response schema-version="{SCHEMA_VERSION}"
      response-id="xml-1" authored-at="2026-08-30T10:00:00Z">
      <answer item-path="HEIGHT" unit="cm"><value>171.5</value></answer>
      <answer item-path="CONSENT"><value>true</value></answer>
    </ehrfs-form-response>""".encode()
    events = adapter.parse_response(
        definition,
        response_xml,
        establishment_id="site-a",
        patient_pseudonym="p-1",
        evidence_object_key="raw/response.xml",
    )
    by_path = {event.item_path: event for event in events}
    assert by_path["HEIGHT"].value == 171.5
    assert by_path["CONSENT"].value is True
    assert by_path["HEIGHT"].evidence[0].source_locator == "/ehrfs-form-response/answer[1]"
    with pytest.raises(DomainError, match="malformed or unsafe"):
        adapter.parse_definition(
            b"<!DOCTYPE x [<!ENTITY e SYSTEM 'file:///etc/passwd'>]><x>&e;</x>"
        )


def _zip(entries: list[tuple[str, bytes]], *, compressed: bool = False) -> bytes:
    target = BytesIO()
    with ZipFile(target, "w", ZIP_DEFLATED if compressed else 0) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return target.getvalue()


def test_archive_inspection_is_bounded_and_never_extracts_paths() -> None:
    entries = extract_safe_zip(_zip([("forms/a.json", b"{}"), ("docs/a.pdf", b"%PDF-")]))
    assert [(entry.name, entry.content) for entry in entries] == [
        ("forms/a.json", b"{}"),
        ("docs/a.pdf", b"%PDF-"),
    ]
    with pytest.raises(DomainError, match="logical root"):
        extract_safe_zip(_zip([("../escape.json", b"{}")]))
    with pytest.raises(DomainError, match="Nested archives"):
        extract_safe_zip(_zip([("nested.zip", b"PK")]))
    with pytest.raises(DomainError, match="too many"):
        extract_safe_zip(_zip([("a", b"a"), ("b", b"b")]), maximum_entries=1)
    with pytest.raises(DomainError, match="expansion exceeds"):
        extract_safe_zip(_zip([("a", b"abcd")]), maximum_total_bytes=3)
    with pytest.raises(DomainError, match="ratio"):
        extract_safe_zip(
            _zip([("large.txt", b"0" * 10_000)], compressed=True),
            maximum_compression_ratio=2,
        )


def test_archive_rejects_symlinks_and_invalid_content() -> None:
    target = BytesIO()
    link = ZipInfo("link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with ZipFile(target, "w") as archive:
        archive.writestr(link, "target")
    with pytest.raises(DomainError, match="links"):
        extract_safe_zip(target.getvalue())
    with pytest.raises(DomainError, match="valid ZIP"):
        extract_safe_zip(b"not-a-zip")
    with pytest.raises(DomainError, match="ambiguous"):
        extract_safe_zip(_zip([("unsafe\\name", b"x")]))
    with pytest.raises(DomainError, match="member exceeds"):
        extract_safe_zip(_zip([("large", b"abcd")]), maximum_entry_bytes=3)
    duplicate = BytesIO()
    with pytest.warns(UserWarning, match="Duplicate"), ZipFile(duplicate, "w") as archive:
        archive.writestr("same", b"first")
        archive.writestr("same", b"second")
    with pytest.raises(DomainError, match="repeats"):
        extract_safe_zip(duplicate.getvalue())

    encrypted = ZipInfo("secret")
    encrypted.flag_bits = 0x1
    encrypted.file_size = encrypted.compress_size = 1
    with pytest.raises(DomainError, match="Encrypted"):
        _validate_member(
            encrypted,
            names=set(),
            maximum_entry_bytes=10,
            maximum_compression_ratio=10,
        )


def test_structured_response_requires_timezone_and_prior_for_correction() -> None:
    with pytest.raises(DomainError, match="response is invalid"):
        _parse_json(
            allergy_form(),
            _response(
                "bad-correction",
                [{"item_path": "Q1", "value": "Oui"}],
                lifecycle_status="CORRECTED",
            ),
        )
    with pytest.raises(DomainError, match="response is invalid"):
        _parse_json(
            allergy_form(),
            _response(
                "naive",
                [{"item_path": "Q1", "value": "Oui"}],
                authored_at="2026-08-30T10:00:00",
            ),
        )
    assert datetime.now(UTC).utcoffset() is not None


def test_structured_scalar_coercion_is_explicit_and_bounded() -> None:
    aware = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)
    assert _coerce_value(None, "string") is None
    assert _coerce_value(False, "boolean") is False
    assert _coerce_value("false", "boolean") is False
    assert _coerce_value("42", "integer") == 42
    assert _coerce_value("72.5", "decimal") == Decimal("72.5")
    assert _coerce_value("text", "text") == "text"
    assert _coerce_value(date(2026, 8, 30), "date") == date(2026, 8, 30)
    assert _coerce_value("2026-08-30", "date") == date(2026, 8, 30)
    assert _coerce_value(aware, "datetime") == aware
    assert _coerce_value("2026-08-30T10:00:00Z", "datetime") == aware

    invalid_values: tuple[tuple[object, DataType], ...] = (
        ("yes", "boolean"),
        (True, "integer"),
        (1.2, "integer"),
        (True, "decimal"),
        ("NaN", "decimal"),
        (7, "string"),
        (aware, "date"),
        ("not-a-date", "date"),
        (aware.replace(tzinfo=None), "datetime"),
        (7, "datetime"),
        ("not-a-datetime", "datetime"),
        ("value", "group"),
    )
    for value, data_type in invalid_values:
        with pytest.raises(DomainError, match=r"[Vv]alue|Group"):
            _coerce_value(value, data_type)


def test_structured_json_rejects_malformed_contracts() -> None:
    adapter = JsonFormAdapter()
    for payload in (b"{broken", b"[]", b"\xff"):
        with pytest.raises(DomainError, match="JSON"):
            adapter.parse_definition(payload)
    with pytest.raises(DomainError, match="definition is invalid"):
        adapter.parse_definition(_json({"schema_version": SCHEMA_VERSION, "form": {}}))
    with pytest.raises(DomainError, match="response is invalid"):
        _parse_json(allergy_form(), _json({"schema_version": SCHEMA_VERSION}))


def test_structured_xml_rejects_malformed_definition_contracts() -> None:
    adapter = XmlFormAdapter()
    base = (
        f'<ehrfs-form-definition schema-version="{SCHEMA_VERSION}" ehr-product="x" '
        'ehr-version="1" form-id="f" form-family="f" version="1" title="F"'
    )
    invalid_definitions: tuple[tuple[bytes, str], ...] = (
        (b"<other />", "must be"),
        (
            f'<ehrfs-form-definition schema-version="{SCHEMA_VERSION}" />'.encode(),
            "requires ehr-product",
        ),
        (
            f'{base} source-order-semantic="maybe"></ehrfs-form-definition>'.encode(),
            "Invalid XML boolean",
        ),
        (
            f'{base}><item id="Q" data-type="reference" /></ehrfs-form-definition>'.encode(),
            "Unsupported item type",
        ),
        (
            (
                f'{base}><item id="Q" data-type="string"><condition source-path="Q" '
                'operator="eq" expected-json="not-json" /></item></ehrfs-form-definition>'
            ).encode(),
            "Condition value",
        ),
        (
            f'{base}><item id="G" data-type="group" /></ehrfs-form-definition>'.encode(),
            "item definition is invalid",
        ),
        (
            (
                f'{base}><item id="A" path="Q" data-type="string" />'
                '<item id="B" path="Q" data-type="string" /></ehrfs-form-definition>'
            ).encode(),
            "form definition is invalid",
        ),
    )
    for payload, message in invalid_definitions:
        with pytest.raises(DomainError, match=message):
            adapter.parse_definition(payload)


def test_xml_nested_items_options_conditions_and_response_errors() -> None:
    adapter = XmlFormAdapter()
    definition = adapter.parse_definition(
        f"""<ehrfs-form-definition schema-version="{SCHEMA_VERSION}" ehr-product="x"
        ehr-version="1" form-id="nested" form-family="nested" version="1" title="Nested">
        <item id="Q1" data-type="coding" required="true" order="2">
          <option code="yes" display="Yes" system="urn:test" />
        </item>
        <item id="G" data-type="group" repeats="true">
          <item id="Q2" data-type="string">
            <condition source-path="Q1" operator="eq" expected-json="&quot;yes&quot;" />
          </item>
        </item>
        </ehrfs-form-definition>""".encode()
    )
    assert definition.items[0].value_options[0].system == "urn:test"
    assert definition.items[1].children[0].path == "G/Q2"
    root = (
        f'<ehrfs-form-response schema-version="{SCHEMA_VERSION}" response-id="r" '
        'authored-at="2026-08-30T10:00:00Z"'
    )
    invalid_responses: tuple[tuple[str, str], ...] = (
        ("><answer><value>x</value></answer></ehrfs-form-response>", "requires item-path"),
        (
            '><answer item-path="Q1" enabled="maybe"><value>yes</value></answer>'
            "</ehrfs-form-response>",
            "Invalid XML boolean",
        ),
        (' lifecycle-status="bad"></ehrfs-form-response>', "response is invalid"),
        (' source-sequence="bad"></ehrfs-form-response>', "response is invalid"),
    )
    for fragment, message in invalid_responses:
        with pytest.raises(DomainError, match=message):
            adapter.parse_response(
                definition,
                f"{root}{fragment}".encode(),
                establishment_id="site-a",
                patient_pseudonym="p-1",
                evidence_object_key="raw/error.xml",
            )


def test_lifecycle_resolution_rejects_invalid_immutable_chains() -> None:
    original = _parse_json(
        allergy_form(),
        _response("lifecycle-original", [{"item_path": "Q1", "value": "Oui"}]),
    )[0]
    with pytest.raises(DomainError) as duplicate_error:
        resolve_lifecycle((original, original))
    assert (duplicate_error.value.code, duplicate_error.value.message) == (
        "DUPLICATE_EVENT_ID",
        "Lifecycle input contains duplicate event identities",
    )

    def corrected(
        target_id: UUID = original.event_id, **event_changes: object
    ) -> CanonicalAnswerEvent:
        return original.model_copy(
            update={
                "event_id": uuid4(),
                "lifecycle": (
                    LifecycleEvent(
                        status=LifecycleStatus.CORRECTED,
                        occurred_at=datetime.now(UTC),
                        source_sequence=2,
                        supersedes_event_id=target_id,
                    ),
                ),
                **event_changes,
            }
        )

    with pytest.raises(DomainError) as outside_batch_error:
        resolve_lifecycle((original, corrected(uuid4())))
    assert (outside_batch_error.value.code, outside_batch_error.value.message) == (
        "INVALID_SUPERSESSION",
        "Correction or void references an event outside the source batch",
    )
    self_link = corrected()
    self_link = self_link.model_copy(
        update={
            "lifecycle": (
                self_link.lifecycle[0].model_copy(
                    update={"supersedes_event_id": self_link.event_id}
                ),
            )
        }
    )
    with pytest.raises(DomainError) as self_link_error:
        resolve_lifecycle((self_link,))
    assert (self_link_error.value.code, self_link_error.value.message) == (
        "INVALID_SUPERSESSION",
        "An event cannot supersede itself",
    )
    with pytest.raises(DomainError) as mismatched_identity_error:
        resolve_lifecycle((original, corrected(patient_pseudonym="different")))
    assert (mismatched_identity_error.value.code, mismatched_identity_error.value.message) == (
        "INVALID_SUPERSESSION",
        "Supersession must remain within one patient, form item, and repeat instance",
    )
    with pytest.raises(DomainError) as ambiguous_error:
        resolve_lifecycle((original, corrected(), corrected()))
    assert (ambiguous_error.value.code, ambiguous_error.value.message) == (
        "AMBIGUOUS_SUPERSESSION",
        "One source event cannot be superseded by multiple current events",
    )

    mixed_lifecycle = corrected()
    mixed_lifecycle = mixed_lifecycle.model_copy(
        update={
            "lifecycle": (
                LifecycleEvent(
                    status=LifecycleStatus.SIGNED,
                    occurred_at=datetime.now(UTC),
                    source_sequence=1,
                ),
                mixed_lifecycle.lifecycle[0],
            )
        }
    )
    assert resolve_lifecycle((original, mixed_lifecycle))[0].state == AnswerState.SUPERSEDED

    first = corrected()
    second = corrected(first.event_id)
    first = first.model_copy(
        update={
            "lifecycle": (
                first.lifecycle[0].model_copy(update={"supersedes_event_id": second.event_id}),
            )
        }
    )
    with pytest.raises(DomainError) as cycle_error:
        resolve_lifecycle((first, second))
    assert (cycle_error.value.code, cycle_error.value.message) == (
        "CYCLIC_SUPERSESSION",
        "Lifecycle supersession contains a cycle",
    )
