from __future__ import annotations

import pytest
from scripts.check_critical_coverage import (
    CRITICAL_MODULES,
    CriticalCoverageError,
    validate_critical_coverage,
)


def _report(*, missing_lines: int = 0, missing_branches: int = 0) -> dict[str, object]:
    return {
        "files": {
            module: {
                "summary": {
                    "missing_lines": missing_lines,
                    "missing_branches": missing_branches,
                }
            }
            for module in CRITICAL_MODULES
        }
    }


def test_critical_coverage_gate_accepts_complete_report() -> None:
    assert validate_critical_coverage(_report()) == {
        "critical_modules": len(CRITICAL_MODULES),
        "statements": 1.0,
        "branches": 1.0,
    }


@pytest.mark.parametrize("field", ["missing_lines", "missing_branches"])
def test_critical_coverage_gate_rejects_incomplete_report(field: str) -> None:
    report = _report(**{field: 1})
    with pytest.raises(CriticalCoverageError, match="critical coverage failed"):
        validate_critical_coverage(report)


def test_critical_coverage_gate_rejects_malformed_report() -> None:
    with pytest.raises(CriticalCoverageError, match="no files mapping"):
        validate_critical_coverage({})
    report = _report()
    files = report["files"]
    assert isinstance(files, dict)
    files.pop(CRITICAL_MODULES[0])
    with pytest.raises(CriticalCoverageError, match="missing from report"):
        validate_critical_coverage(report)
    files[CRITICAL_MODULES[0]] = {}
    with pytest.raises(CriticalCoverageError, match="missing summary"):
        validate_critical_coverage(report)
