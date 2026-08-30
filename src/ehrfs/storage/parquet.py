"""Bounded canonical Parquet partitions and checksummed manifests."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from ehrfs.domain.identity import sha256_hex
from ehrfs.domain.models import CanonicalAnswerEvent


@dataclass(frozen=True, slots=True)
class ParquetPartition:
    path: Path
    row_count: int
    checksum_sha256: str


def _row(event: CanonicalAnswerEvent) -> dict[str, object]:
    return {
        "event_id": str(event.event_id),
        "establishment_id": event.establishment_id,
        "patient_pseudonym": event.patient_pseudonym,
        "encounter_pseudonym": event.encounter_pseudonym,
        "form_id": event.form_id,
        "form_version": event.form_version,
        "source_fingerprint": event.source_fingerprint,
        "compatibility_fingerprint": event.compatibility_fingerprint,
        "item_path": event.item_path,
        "group_instance": event.group_instance,
        "state": event.state,
        "value_json": event.model_dump_json(exclude={"evidence", "lifecycle"}),
        "authored_at": event.authored_at,
        "evidence_json": "[" + ",".join(item.model_dump_json() for item in event.evidence) + "]",
    }


class CanonicalParquetWriter:
    def __init__(self, root: Path, *, partition_rows: int = 50_000) -> None:
        if partition_rows < 1:
            msg = "Parquet partitions require at least one row"
            raise ValueError(msg)
        self._root = root
        self._partition_rows = partition_rows

    def write(
        self,
        events: Iterable[CanonicalAnswerEvent],
        *,
        establishment_id: str,
        batch_id: str,
        fingerprint: str,
        period: str = "unspecified",
    ) -> tuple[ParquetPartition, ...]:
        destination = (
            self._root
            / f"establishment_id={establishment_id}"
            / f"period={period}"
            / f"batch_id={batch_id}"
            / f"fingerprint={fingerprint}"
        )
        destination.mkdir(parents=True, exist_ok=True)
        partitions: list[ParquetPartition] = []
        rows: list[dict[str, object]] = []

        def flush() -> None:
            if not rows:
                return
            path = destination / f"part-{len(partitions):05d}.parquet"
            pl.DataFrame(rows).write_parquet(
                path,
                compression="zstd",
                statistics=True,
            )
            content = path.read_bytes()
            partitions.append(
                ParquetPartition(
                    path=path,
                    row_count=len(rows),
                    checksum_sha256=sha256_hex(content),
                )
            )
            rows.clear()

        for event in events:
            rows.append(_row(event))
            if len(rows) >= self._partition_rows:
                flush()
        flush()
        return tuple(partitions)
