"""Enforce complete statement and branch coverage for publication-critical code."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

CRITICAL_MODULES = (
    "src/ehrfs/canonical/state.py",
    "src/ehrfs/catalog/coverage.py",
    "src/ehrfs/domain/identity.py",
    "src/ehrfs/fingerprinting/service.py",
    "src/ehrfs/lineage/graph.py",
    "src/ehrfs/mapping/releases.py",
    "src/ehrfs/mapping/resolver.py",
    "src/ehrfs/quality/engine.py",
    "src/ehrfs/standardization/conversion.py",
)


class CriticalCoverageError(RuntimeError):
    """Raised when the coverage report cannot prove the critical gate."""

    @classmethod
    def missing_files(cls) -> CriticalCoverageError:
        return cls("coverage report has no files mapping")

    @classmethod
    def incomplete(cls, failures: list[str]) -> CriticalCoverageError:
        return cls("critical coverage failed: " + "; ".join(failures))


def validate_critical_coverage(report: dict[str, Any]) -> dict[str, object]:
    files = report.get("files")
    if not isinstance(files, dict):
        raise CriticalCoverageError.missing_files()

    failures: list[str] = []
    for module in CRITICAL_MODULES:
        module_report = files.get(module)
        if not isinstance(module_report, dict):
            failures.append(f"{module}: missing from report")
            continue
        summary = module_report.get("summary")
        if not isinstance(summary, dict):
            failures.append(f"{module}: missing summary")
            continue
        missing_lines = summary.get("missing_lines")
        missing_branches = summary.get("missing_branches")
        if missing_lines != 0 or missing_branches != 0:
            failures.append(
                f"{module}: {missing_lines!r} missing lines, {missing_branches!r} missing branches"
            )

    if failures:
        raise CriticalCoverageError.incomplete(failures)
    return {"critical_modules": len(CRITICAL_MODULES), "statements": 1.0, "branches": 1.0}


def main() -> int:
    report_path = Path(sys.argv[1] if len(sys.argv) > 1 else "coverage.json")
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        result = validate_critical_coverage(report)
    except (OSError, json.JSONDecodeError, CriticalCoverageError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
