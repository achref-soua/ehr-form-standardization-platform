from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from ehrfs.domain.models import FormDefinition, ItemDefinition
from ehrfs.fingerprinting.service import fingerprint_form


def _form(labels: tuple[str, str], *, semantic_order: bool) -> FormDefinition:
    return FormDefinition(
        ehr_product="Demo",
        ehr_version="1",
        form_id="vitals",
        form_family="vitals",
        version="1",
        title="Vitals",
        source_order_semantic=semantic_order,
        items=(
            ItemDefinition(
                item_id="a",
                path="a",
                label=labels[0],
                data_type="integer",
                order=0,
            ),
            ItemDefinition(
                item_id="b",
                path="b",
                label=labels[1],
                data_type="integer",
                order=1,
            ),
        ),
    )


@given(st.text(min_size=1), st.text(min_size=1))
def test_fingerprint_is_stable(labels: str, second_label: str) -> None:
    form = _form((labels, second_label), semantic_order=True)
    assert fingerprint_form(form) == fingerprint_form(form.model_copy(deep=True))


def test_label_change_changes_both_fingerprints() -> None:
    original = fingerprint_form(_form(("Systolic", "Diastolic"), semantic_order=True))
    changed = fingerprint_form(_form(("Systolic pressure", "Diastolic"), semantic_order=True))
    assert original.source != changed.source
    assert original.compatibility != changed.compatibility


def test_unordered_source_normalizes_item_order() -> None:
    original = _form(("A", "B"), semantic_order=False)
    reversed_items = tuple(reversed(original.items))
    reordered = original.model_copy(update={"items": reversed_items})
    assert fingerprint_form(original) == fingerprint_form(reordered)


def test_semantic_order_change_changes_source_fingerprint() -> None:
    original = _form(("A", "B"), semantic_order=True)
    changed_items = (
        original.items[0].model_copy(update={"order": 1}),
        original.items[1].model_copy(update={"order": 0}),
    )
    changed = original.model_copy(update={"items": changed_items})
    assert fingerprint_form(original).source != fingerprint_form(changed).source
