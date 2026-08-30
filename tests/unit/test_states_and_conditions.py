from __future__ import annotations

import pytest

from ehrfs.canonical.conditions import conditions_satisfied
from ehrfs.canonical.state import derive_answer_state
from ehrfs.domain.enums import AnswerState, LifecycleStatus
from ehrfs.domain.models import DisplayCondition


@pytest.mark.parametrize(
    ("present", "enabled", "value", "lifecycle", "expected"),
    [
        (True, True, "Oui", LifecycleStatus.SIGNED, AnswerState.PRESENT),
        (True, True, "Non", LifecycleStatus.SIGNED, AnswerState.EXPLICITLY_ABSENT),
        (True, True, "inconnu", LifecycleStatus.SIGNED, AnswerState.UNKNOWN),
        (True, True, "n/a", LifecycleStatus.SIGNED, AnswerState.NOT_APPLICABLE),
        (True, True, None, LifecycleStatus.SIGNED, AnswerState.NOT_RECORDED),
        (False, True, None, LifecycleStatus.SIGNED, AnswerState.NOT_RECORDED),
        (False, False, None, LifecycleStatus.SIGNED, AnswerState.NOT_DISPLAYED_BY_FORM_LOGIC),
        (True, True, "Oui", LifecycleStatus.VOIDED, AnswerState.VOIDED),
        (True, True, "Oui", LifecycleStatus.DELETED, AnswerState.DELETED),
        (True, True, "Oui", LifecycleStatus.DRAFT, AnswerState.NOT_RECORDED),
    ],
)
def test_answer_state_derivation(
    present: bool,
    enabled: bool,
    value: object | None,
    lifecycle: LifecycleStatus,
    expected: AnswerState,
) -> None:
    assert (
        derive_answer_state(
            response_present=present,
            enabled=enabled,
            raw_value=value,
            lifecycle_status=lifecycle,
        )
        == expected
    )


def test_all_conditions_must_pass_by_default() -> None:
    conditions = (
        DisplayCondition(source_item_path="Q1", operator="eq", expected="Oui"),
        DisplayCondition(source_item_path="AGE", operator="gte", expected=18),
    )
    assert conditions_satisfied(conditions, {"Q1": "Oui", "AGE": 42})
    assert not conditions_satisfied(conditions, {"Q1": "Non", "AGE": 42})


def test_any_condition_behavior() -> None:
    conditions = (
        DisplayCondition(source_item_path="Q1", operator="eq", expected="Oui"),
        DisplayCondition(source_item_path="Q2", operator="exists", expected=True),
    )
    assert conditions_satisfied(conditions, {"Q1": "Non", "Q2": "value"}, behavior="any")


def test_unknown_condition_behavior_is_rejected() -> None:
    conditions = (DisplayCondition(source_item_path="Q1", operator="eq", expected="Oui"),)
    with pytest.raises(ValueError, match="Unsupported condition behavior"):
        conditions_satisfied(conditions, {"Q1": "Oui"}, behavior="xor")
