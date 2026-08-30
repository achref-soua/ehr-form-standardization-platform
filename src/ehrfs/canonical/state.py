"""Derive explicit states without conflating null-like values."""

from __future__ import annotations

from ehrfs.domain.enums import AnswerState, LifecycleStatus


def derive_answer_state(
    *,
    response_present: bool,
    enabled: bool,
    raw_value: object | None,
    lifecycle_status: LifecycleStatus,
    negative_values: frozenset[str] = frozenset({"false", "non", "no"}),
    unknown_values: frozenset[str] = frozenset({"unknown", "inconnu"}),
    not_applicable_values: frozenset[str] = frozenset({"n/a", "not-applicable"}),
) -> AnswerState:
    if lifecycle_status == LifecycleStatus.DELETED:
        state = AnswerState.DELETED
    elif lifecycle_status == LifecycleStatus.VOIDED:
        state = AnswerState.VOIDED
    elif lifecycle_status == LifecycleStatus.DRAFT:
        state = AnswerState.NOT_RECORDED
    elif not enabled:
        state = AnswerState.NOT_DISPLAYED_BY_FORM_LOGIC
    elif not response_present or raw_value is None or raw_value == "":
        state = AnswerState.NOT_RECORDED
    else:
        normalized = str(raw_value).strip().casefold()
        if normalized in negative_values:
            state = AnswerState.EXPLICITLY_ABSENT
        elif normalized in unknown_values:
            state = AnswerState.UNKNOWN
        elif normalized in not_applicable_values:
            state = AnswerState.NOT_APPLICABLE
        else:
            state = AnswerState.PRESENT
    return state
