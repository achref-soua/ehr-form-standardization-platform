from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")

from scripts.benchmark_100m import run  # noqa: E402


@pytest.mark.performance
def test_benchmark_harness_is_bounded_and_deterministic() -> None:
    first = run(120_000, 50_000)
    second = run(120_000, 50_000)
    assert first.partitions == 3
    assert first.partition_rows == 50_000
    assert first.duplicate_publications == 0
    assert first.rss_within_limit
    assert first.deterministic_sample_verified
    assert first.canonical_parquet_checksum_sha256 == second.canonical_parquet_checksum_sha256
