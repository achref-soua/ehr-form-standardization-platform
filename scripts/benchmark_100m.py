"""Measured, bounded 100-million canonical-answer event benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import resource
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import cast

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts/benchmarks/answer-events-100m.json"
FOUR_GIB = 4 * 1024**3
NAMESPACE_HIGH = 0x6BA7B8119DAD51D1
PUBLISHABLE_MAX_STATE_CODE = 2
STATE_LABELS = pa.array(
    ["PRESENT", "EXPLICITLY_ABSENT", "UNKNOWN", "UNANSWERED", "NOT_APPLICABLE", "NOT_DISPLAYED"]
)
UNIT_LABELS = pa.array(["none", "kg", "mm[Hg]", "Cel"])
SITE_LABELS = pa.array(["site-a", "site-b", "site-c", "site-d"])


class InvalidBenchmarkArgumentsError(ValueError):
    """Raised when the requested benchmark shape is not positive."""


class PartitionRangeError(RuntimeError):
    """Raised when generated partition ranges are not contiguous."""


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    events: int
    partition_rows: int
    partitions: int
    elapsed_seconds: float
    events_per_second: float
    peak_worker_rss_bytes: int
    rss_limit_bytes: int
    rss_within_limit: bool
    published_events: int
    duplicate_publications: int
    canonical_parquet_checksum_sha256: str
    deterministic_sample_verified: bool
    python: str
    numpy: str
    pyarrow: str
    measured: bool


def _partition(start: int, rows: int, partition_number: int) -> tuple[pa.Table, int]:
    ordinals = np.arange(start, start + rows, dtype=np.uint64)
    identifiers = np.empty((rows, 2), dtype=">u8")
    identifiers[:, 0] = NAMESPACE_HIGH
    identifiers[:, 1] = ordinals
    state_codes = np.remainder(ordinals, len(STATE_LABELS)).astype(np.int8)
    unit_codes = np.remainder(ordinals // 5, len(UNIT_LABELS)).astype(np.int8)
    site_codes = np.remainder(ordinals // 50_000, len(SITE_LABELS)).astype(np.int8)
    values = np.where(state_codes == 0, np.remainder(ordinals, 4000) / 10, np.nan)
    table = pa.table(
        {
            "clinical_event_id": pa.FixedSizeBinaryArray.from_buffers(
                pa.binary(16), rows, [None, pa.py_buffer(identifiers)]
            ),
            "patient_number": pa.array(ordinals // 20),
            "item_code": pa.array(np.remainder(ordinals, 20).astype(np.int16)),
            "answer_state": pa.DictionaryArray.from_arrays(pa.array(state_codes), STATE_LABELS),
            "value_as_number": pa.array(values, from_pandas=True),
            "unit": pa.DictionaryArray.from_arrays(pa.array(unit_codes), UNIT_LABELS),
            "establishment": pa.DictionaryArray.from_arrays(pa.array(site_codes), SITE_LABELS),
            "partition": pa.array(np.full(rows, partition_number, dtype=np.int32)),
        }
    )
    published = int(np.count_nonzero(state_codes <= PUBLISHABLE_MAX_STATE_CODE))
    return table, published


def _serialize(table: pa.Table) -> bytes:
    sink = pa.BufferOutputStream()
    pq.write_table(
        table,
        sink,
        compression="zstd",
        compression_level=3,
        row_group_size=table.num_rows,
        use_dictionary=True,
        write_statistics=True,
    )
    return cast(bytes, sink.getvalue().to_pybytes())


def run(events: int, partition_rows: int) -> BenchmarkReport:
    if events <= 0 or partition_rows <= 0:
        raise InvalidBenchmarkArgumentsError
    started = perf_counter()
    digest = hashlib.sha256()
    published_events = 0
    partitions = 0
    previous_end = 0
    sample_verified = False
    for start in range(0, events, partition_rows):
        rows = min(partition_rows, events - start)
        if start != previous_end:
            raise PartitionRangeError
        table, published = _partition(start, rows, partitions)
        serialized = _serialize(table)
        digest.update(hashlib.sha256(serialized).digest())
        if partitions == 0:
            sample_verified = serialized == _serialize(_partition(start, rows, partitions)[0])
        published_events += published
        partitions += 1
        previous_end = start + rows
    elapsed = perf_counter() - started
    peak_rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    return BenchmarkReport(
        events=events,
        partition_rows=partition_rows,
        partitions=partitions,
        elapsed_seconds=round(elapsed, 6),
        events_per_second=round(events / elapsed, 2),
        peak_worker_rss_bytes=peak_rss_bytes,
        rss_limit_bytes=FOUR_GIB,
        rss_within_limit=peak_rss_bytes <= FOUR_GIB,
        published_events=published_events,
        duplicate_publications=0 if previous_end == events else events - previous_end,
        canonical_parquet_checksum_sha256=digest.hexdigest(),
        deterministic_sample_verified=sample_verified,
        python=platform.python_version(),
        numpy=np.__version__,
        pyarrow=pa.__version__,
        measured=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=int, default=100_000_000)
    parser.add_argument("--partition-rows", type=int, default=50_000)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()
    report = run(arguments.events, arguments.partition_rows)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(asdict(report), indent=2, sort_keys=True) + "\n"
    arguments.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    if not report.rss_within_limit or report.duplicate_publications:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
