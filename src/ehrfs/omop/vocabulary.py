"""Strict, local-only import of user-provided OHDSI Athena vocabulary files."""

from __future__ import annotations

import csv
import hashlib
from collections.abc import Iterator, Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

from pydantic import Field
from sqlalchemy import Table, select
from sqlalchemy.orm import Session

from ehrfs.domain.models import DomainModel
from ehrfs.storage.tables import (
    OmopConceptClassRow,
    OmopConceptRow,
    OmopDomainRow,
    OmopVocabularyRow,
    VocabularyImportRow,
)

MAX_ATHENA_FILE_BYTES = 20 * 1024 * 1024 * 1024
DEFAULT_BATCH_SIZE = 10_000
COMPACT_DATE_LENGTH = 8


class AthenaImportError(ValueError):
    """Raised when an Athena snapshot is unsafe, incomplete, or inconsistent."""

    def __init__(self, code: str, *details: object) -> None:
        messages = {
            "missing_file": "missing required Athena file: {}",
            "not_regular": "Athena input must be a regular non-symlink file: {}",
            "escapes": "Athena file escapes the selected directory: {}",
            "too_large": "Athena file exceeds the 20 GiB safety limit: {}",
            "invalid_date": "invalid date in {} row {}: {}",
            "too_many_fields": "too many fields in {} row {}",
            "missing_value": "missing {} in {} row {}",
            "empty_value": "empty {} in {} row {}",
            "invalid_integer": "invalid integer {} in {} row {}",
            "invalid_header": "invalid header in {}: expected {}, received {}",
            "unsafe_directory": "Athena input must be a non-symlink directory",
            "no_standard_concept": "CONCEPT.csv must contain at least one standard concept",
            "bad_batch_size": "batch_size must be positive",
            "release_rebound": "release_id is already bound to a different Athena checksum",
            "file_changed": "Athena file changed after validation: {}",
        }
        super().__init__(messages[code].format(*details))


class AthenaFileManifest(DomainModel):
    name: str
    bytes: int = Field(ge=0)
    rows: int = Field(ge=0)
    checksum_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AthenaSnapshot(DomainModel):
    release_id: str
    vocabulary_version: str
    source_checksum_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    files: tuple[AthenaFileManifest, ...]
    concept_count: int = Field(ge=0)
    standard_concept_count: int = Field(ge=0)


FILE_COLUMNS: dict[str, tuple[str, ...]] = {
    "DOMAIN.csv": ("domain_id", "domain_name", "domain_concept_id"),
    "VOCABULARY.csv": (
        "vocabulary_id",
        "vocabulary_name",
        "vocabulary_reference",
        "vocabulary_version",
        "vocabulary_concept_id",
    ),
    "CONCEPT_CLASS.csv": (
        "concept_class_id",
        "concept_class_name",
        "concept_class_concept_id",
    ),
    "CONCEPT.csv": (
        "concept_id",
        "concept_name",
        "domain_id",
        "vocabulary_id",
        "concept_class_id",
        "standard_concept",
        "concept_code",
        "valid_start_date",
        "valid_end_date",
        "invalid_reason",
    ),
}
TABLE_BY_FILE: dict[str, Table] = {
    "DOMAIN.csv": cast(Table, OmopDomainRow.__table__),
    "VOCABULARY.csv": cast(Table, OmopVocabularyRow.__table__),
    "CONCEPT_CLASS.csv": cast(Table, OmopConceptClassRow.__table__),
    "CONCEPT.csv": cast(Table, OmopConceptRow.__table__),
}
INTEGER_COLUMNS = {
    "concept_id",
    "domain_concept_id",
    "vocabulary_concept_id",
    "concept_class_concept_id",
}
DATE_COLUMNS = {"valid_start_date", "valid_end_date"}
REQUIRED_VALUE_COLUMNS = {
    "domain_id",
    "domain_name",
    "domain_concept_id",
    "vocabulary_id",
    "vocabulary_name",
    "vocabulary_concept_id",
    "concept_class_id",
    "concept_class_name",
    "concept_class_concept_id",
    "concept_id",
    "concept_name",
    "concept_code",
    "valid_start_date",
    "valid_end_date",
}


def _secure_file(root: Path, name: str) -> Path:
    path = root / name
    if not path.exists():
        raise AthenaImportError("missing_file", name)
    if path.is_symlink() or not path.is_file():
        raise AthenaImportError("not_regular", name)
    resolved = path.resolve(strict=True)
    if resolved.parent != root:
        raise AthenaImportError("escapes", name)
    if resolved.stat().st_size > MAX_ATHENA_FILE_BYTES:
        raise AthenaImportError("too_large", name)
    return resolved


def _file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _date_value(value: str, *, file_name: str, row_number: int) -> date:
    normalized = value.strip()
    try:
        if len(normalized) == COMPACT_DATE_LENGTH and normalized.isdigit():
            return date(int(normalized[:4]), int(normalized[4:6]), int(normalized[6:]))
        return date.fromisoformat(normalized)
    except ValueError as error:
        raise AthenaImportError("invalid_date", file_name, row_number, normalized) from error


def _typed_row(
    values: Mapping[str | None, str | list[str] | None],
    *,
    file_name: str,
    row_number: int,
) -> dict[str, Any]:
    if None in values:
        raise AthenaImportError("too_many_fields", file_name, row_number)
    result: dict[str, Any] = {}
    for column in FILE_COLUMNS[file_name]:
        raw = values.get(column)
        if not isinstance(raw, str):
            raise AthenaImportError("missing_value", column, file_name, row_number)
        value = raw.strip()
        if not value:
            if column in REQUIRED_VALUE_COLUMNS:
                raise AthenaImportError("empty_value", column, file_name, row_number)
            result[column] = None
        elif column in INTEGER_COLUMNS:
            try:
                result[column] = int(value)
            except ValueError as error:
                raise AthenaImportError("invalid_integer", column, file_name, row_number) from error
        elif column in DATE_COLUMNS:
            result[column] = _date_value(value, file_name=file_name, row_number=row_number)
        else:
            result[column] = value
    return result


def iter_athena_rows(path: Path, *, file_name: str) -> Iterator[dict[str, Any]]:
    """Yield validated, typed rows without retaining the snapshot in memory."""
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        actual = tuple(reader.fieldnames or ())
        expected = FILE_COLUMNS[file_name]
        if actual != expected:
            raise AthenaImportError("invalid_header", file_name, expected, actual)
        for row_number, row in enumerate(reader, start=2):
            yield _typed_row(row, file_name=file_name, row_number=row_number)


def inspect_athena_snapshot(
    directory: Path,
    *,
    release_id: str,
    vocabulary_version: str,
) -> AthenaSnapshot:
    """Validate and checksum all required files before opening a database transaction."""
    root = directory.resolve(strict=True)
    if not root.is_dir() or directory.is_symlink():
        raise AthenaImportError("unsafe_directory")
    manifests: list[AthenaFileManifest] = []
    combined = hashlib.sha256()
    concept_count = 0
    standard_count = 0
    for name in FILE_COLUMNS:
        path = _secure_file(root, name)
        checksum = _file_checksum(path)
        rows = 0
        for row in iter_athena_rows(path, file_name=name):
            rows += 1
            if name == "CONCEPT.csv" and row["standard_concept"] == "S":
                standard_count += 1
        if name == "CONCEPT.csv":
            concept_count = rows
        manifests.append(
            AthenaFileManifest(
                name=name,
                bytes=path.stat().st_size,
                rows=rows,
                checksum_sha256=checksum,
            )
        )
        combined.update(name.encode("utf-8"))
        combined.update(b"\0")
        combined.update(bytes.fromhex(checksum))
    if concept_count == 0 or standard_count == 0:
        raise AthenaImportError("no_standard_concept")
    return AthenaSnapshot(
        release_id=release_id,
        vocabulary_version=vocabulary_version,
        source_checksum_sha256=combined.hexdigest(),
        files=tuple(manifests),
        concept_count=concept_count,
        standard_concept_count=standard_count,
    )


def _insert_file(
    session: Session,
    root: Path,
    file_name: str,
    *,
    batch_size: int,
) -> None:
    if batch_size < 1:
        raise AthenaImportError("bad_batch_size")
    batch: list[dict[str, Any]] = []
    for row in iter_athena_rows(root / file_name, file_name=file_name):
        batch.append(row)
        if len(batch) == batch_size:
            session.execute(TABLE_BY_FILE[file_name].insert(), batch)
            batch.clear()
    if batch:
        session.execute(TABLE_BY_FILE[file_name].insert(), batch)


def load_athena_snapshot(
    session: Session,
    directory: Path,
    snapshot: AthenaSnapshot,
    *,
    loaded_by: str,
    loaded_at: datetime | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> bool:
    """Atomically load a validated snapshot; return false for an idempotent replay."""
    existing = session.scalar(
        select(VocabularyImportRow).where(VocabularyImportRow.release_id == snapshot.release_id)
    )
    if existing is not None:
        if existing.source_checksum_sha256 != snapshot.source_checksum_sha256:
            raise AthenaImportError("release_rebound")
        return False
    root = directory.resolve(strict=True)
    for file_manifest in snapshot.files:
        path = _secure_file(root, file_manifest.name)
        if _file_checksum(path) != file_manifest.checksum_sha256:
            raise AthenaImportError("file_changed", file_manifest.name)
        _insert_file(session, root, file_manifest.name, batch_size=batch_size)
    session.add(
        VocabularyImportRow(
            release_id=snapshot.release_id,
            vocabulary_version=snapshot.vocabulary_version,
            source_checksum_sha256=snapshot.source_checksum_sha256,
            source_manifest_json=snapshot.model_dump(mode="json"),
            concept_count=snapshot.concept_count,
            standard_concept_count=snapshot.standard_concept_count,
            loaded_by=loaded_by,
            loaded_at=loaded_at or datetime.now(UTC),
        )
    )
    return True
