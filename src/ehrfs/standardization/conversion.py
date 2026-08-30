"""Bounded, declarative unit and local-value conversion."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from ehrfs.domain.models import ScalarValue
from ehrfs.mapping.models import UnitRule


def normalize_source_value(value: ScalarValue) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip()


def convert_unit(value: ScalarValue, rule: UnitRule) -> Decimal:
    if isinstance(value, bool):
        msg = "Boolean values cannot be converted as quantities"
        raise TypeError(msg)
    try:
        numeric = Decimal(str(value))
        multiplier = Decimal(rule.multiplier)
        offset = Decimal(rule.offset)
    except InvalidOperation as error:
        msg = "Unit conversion requires finite decimal values"
        raise ValueError(msg) from error
    result = numeric * multiplier + offset
    if not result.is_finite():
        msg = "Unit conversion produced a non-finite result"
        raise ValueError(msg)
    return result.normalize()
