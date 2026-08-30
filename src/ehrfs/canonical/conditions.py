"""A deliberately bounded display-condition evaluator."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from ehrfs.domain.models import DisplayCondition, ScalarValue


def _compare(actual: ScalarValue | None, condition: DisplayCondition) -> bool:
    if condition.operator == "exists":
        return (actual is not None) is condition.expected
    if actual is None:
        return False
    expected = condition.expected
    if condition.operator == "eq":
        return actual == expected
    if condition.operator == "ne":
        return actual != expected
    try:
        left = Decimal(str(actual))
        right = Decimal(str(expected))
    except InvalidOperation:
        return False
    if condition.operator == "gt":
        result = left > right
    elif condition.operator == "gte":
        result = left >= right
    elif condition.operator == "lt":
        result = left < right
    else:
        result = left <= right
    return result


def conditions_satisfied(
    conditions: tuple[DisplayCondition, ...],
    answers_by_path: Mapping[str, ScalarValue | None],
    *,
    behavior: str = "all",
) -> bool:
    if not conditions:
        return True
    evaluations = [
        _compare(answers_by_path.get(condition.source_item_path), condition)
        for condition in conditions
    ]
    if behavior == "any":
        return any(evaluations)
    if behavior != "all":
        msg = f"Unsupported condition behavior: {behavior}"
        raise ValueError(msg)
    return all(evaluations)
