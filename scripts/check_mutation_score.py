"""Enforce the machine-readable mutation-testing acceptance gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


class MutationGateError(ValueError):
    """Raised when mutation results are incomplete or below the required score."""

    @classmethod
    def missing_counters(cls) -> MutationGateError:
        return cls("Mutation report is missing required counters")

    @classmethod
    def no_testable_mutations(cls) -> MutationGateError:
        return cls("Mutation report has no testable mutations")

    @classmethod
    def unacceptable_outcomes(cls, outcomes: dict[str, int]) -> MutationGateError:
        return cls(f"Mutation report contains unacceptable outcomes: {outcomes}")

    @classmethod
    def below_threshold(cls, score: float, threshold: float) -> MutationGateError:
        return cls(f"Mutation score {score:.2%} is below the required {threshold:.2%}")


def evaluate(stats: dict[str, Any], *, threshold: float = 0.90) -> dict[str, int | float]:
    required = {
        "killed",
        "survived",
        "total",
        "no_tests",
        "skipped",
        "suspicious",
        "timeout",
        "check_was_interrupted_by_user",
        "segfault",
    }
    if required - stats.keys():
        raise MutationGateError.missing_counters()
    counters = {name: int(stats[name]) for name in required}
    testable = counters["total"] - counters["no_tests"] - counters["skipped"]
    if testable <= 0:
        raise MutationGateError.no_testable_mutations()
    detected = counters["killed"] + counters["timeout"]
    score = detected / testable
    invalid = {
        name: counters[name]
        for name in (
            "survived",
            "no_tests",
            "suspicious",
            "check_was_interrupted_by_user",
            "segfault",
        )
        if counters[name]
    }
    if invalid:
        raise MutationGateError.unacceptable_outcomes(invalid)
    if score < threshold:
        raise MutationGateError.below_threshold(score, threshold)
    return {
        "total": counters["total"],
        "testable": testable,
        "assertion_killed": counters["killed"],
        "timeout_killed": counters["timeout"],
        "score": round(score, 6),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--threshold", type=float, default=0.90)
    arguments = parser.parse_args()
    stats = json.loads(arguments.report.read_text(encoding="utf-8"))
    result = evaluate(stats, threshold=arguments.threshold)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
