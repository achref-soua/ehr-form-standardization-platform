from __future__ import annotations

import pytest
from scripts.check_mutation_score import MutationGateError, evaluate


def _stats(**changes: int) -> dict[str, int]:
    baseline = {
        "killed": 429,
        "survived": 0,
        "total": 559,
        "no_tests": 0,
        "skipped": 0,
        "suspicious": 0,
        "timeout": 130,
        "check_was_interrupted_by_user": 0,
        "segfault": 0,
    }
    return baseline | changes


def test_mutation_gate_accepts_detected_timeout_and_assertion_failures() -> None:
    result = evaluate(_stats())
    assert result == {
        "total": 559,
        "testable": 559,
        "assertion_killed": 429,
        "timeout_killed": 130,
        "score": 1.0,
    }


@pytest.mark.parametrize(
    "stats,message",
    (
        (_stats(survived=1, killed=428), "unacceptable"),
        (_stats(no_tests=1), "unacceptable"),
        (_stats(killed=1, timeout=0), "below"),
        ({"total": 1}, "missing"),
        (_stats(total=0, killed=0, timeout=0), "no testable"),
    ),
)
def test_mutation_gate_rejects_incomplete_or_unsafe_results(
    stats: dict[str, int], message: str
) -> None:
    with pytest.raises(MutationGateError, match=message):
        evaluate(stats)
