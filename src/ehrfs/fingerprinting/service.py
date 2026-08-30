"""Build exact source and mapping-compatibility fingerprints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ehrfs.domain.identity import content_hash
from ehrfs.domain.models import FormDefinition, ItemDefinition


@dataclass(frozen=True, slots=True)
class FormFingerprints:
    source: str
    compatibility: str


def _ordered_items(
    items: tuple[ItemDefinition, ...], *, parent_order_semantic: bool
) -> tuple[ItemDefinition, ...]:
    if parent_order_semantic:
        return tuple(sorted(items, key=lambda item: item.order))
    return tuple(sorted(items, key=lambda item: item.path))


def _item_payload(item: ItemDefinition, *, complete: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "item_id": item.item_id,
        "path": item.path,
        "label": " ".join(item.label.split()),
        "data_type": item.data_type,
        "required": item.required,
        "repeats": item.repeats,
        "unit": item.unit,
        "value_options": [option.model_dump(mode="json") for option in item.value_options],
        "display_conditions": [
            condition.model_dump(mode="json") for condition in item.display_conditions
        ],
        "calculation": item.calculation,
        "children": [
            _item_payload(child, complete=complete)
            for child in _ordered_items(
                item.children,
                parent_order_semantic=item.order_semantic,
            )
        ],
    }
    if complete or item.order_semantic:
        payload["order"] = item.order
    if complete:
        payload["order_semantic"] = item.order_semantic
    return payload


def fingerprint_form(form: FormDefinition) -> FormFingerprints:
    ordered = _ordered_items(form.items, parent_order_semantic=form.source_order_semantic)
    complete_payload = {
        "ehr_product": form.ehr_product,
        "ehr_version": form.ehr_version,
        "form_id": form.form_id,
        "form_family": form.form_family,
        "version": form.version,
        "title": form.title,
        "source_order_semantic": form.source_order_semantic,
        "metadata": form.metadata,
        "items": [_item_payload(item, complete=True) for item in ordered],
    }
    compatibility_payload = {
        "ehr_product": form.ehr_product,
        "form_family": form.form_family,
        "items": [_item_payload(item, complete=False) for item in ordered],
    }
    return FormFingerprints(
        source=content_hash(complete_payload),
        compatibility=content_hash(compatibility_payload),
    )
