from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.orm import Session

from ehrfs.omop.vocabulary import (
    FILE_COLUMNS,
    AthenaImportError,
    inspect_athena_snapshot,
    load_athena_snapshot,
)


def write_athena_snapshot(root: Path) -> None:
    rows: dict[str, list[tuple[str, ...]]] = {
        "DOMAIN.csv": [("Observation", "Observation", "9000001")],
        "VOCABULARY.csv": [("TEST", "Test vocabulary", "project", "1", "9000002")],
        "CONCEPT_CLASS.csv": [("Test", "Test class", "9000003")],
        "CONCEPT.csv": [
            (
                "9100001",
                "Test standard concept",
                "Observation",
                "TEST",
                "Test",
                "S",
                "TEST-1",
                "20260101",
                "2099-12-31",
                "",
            )
        ],
    }
    root.mkdir()
    for name, values in rows.items():
        lines = ["\t".join(FILE_COLUMNS[name]), *("\t".join(row) for row in values)]
        (root / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_inspect_athena_snapshot_is_typed_checksummed_and_deterministic(tmp_path: Path) -> None:
    source = tmp_path / "athena"
    write_athena_snapshot(source)

    first = inspect_athena_snapshot(source, release_id="athena-test-1", vocabulary_version="1")
    second = inspect_athena_snapshot(source, release_id="athena-test-1", vocabulary_version="1")

    assert first == second
    assert first.concept_count == 1
    assert first.standard_concept_count == 1
    assert len(first.files) == 4
    assert all(file.checksum_sha256 for file in first.files)


def test_inspect_athena_snapshot_rejects_unsafe_and_malformed_files(tmp_path: Path) -> None:
    source = tmp_path / "athena"
    write_athena_snapshot(source)
    (source / "CONCEPT.csv").write_text("wrong\theader\n", encoding="utf-8")
    with pytest.raises(AthenaImportError, match="invalid header"):
        inspect_athena_snapshot(source, release_id="broken", vocabulary_version="1")

    (source / "CONCEPT.csv").unlink()
    (source / "CONCEPT.csv").symlink_to(source / "DOMAIN.csv")
    with pytest.raises(AthenaImportError, match="non-symlink"):
        inspect_athena_snapshot(source, release_id="unsafe", vocabulary_version="1")


def test_inspect_athena_snapshot_rejects_invalid_values_and_empty_concepts(tmp_path: Path) -> None:
    source = tmp_path / "athena"
    write_athena_snapshot(source)
    concept = source / "CONCEPT.csv"
    content = concept.read_text(encoding="utf-8")
    concept.write_text(content.replace("20260101", "not-a-date"), encoding="utf-8")
    with pytest.raises(AthenaImportError, match="invalid date"):
        inspect_athena_snapshot(source, release_id="bad-date", vocabulary_version="1")

    concept.write_text("\t".join(FILE_COLUMNS["CONCEPT.csv"]) + "\n", encoding="utf-8")
    with pytest.raises(AthenaImportError, match="at least one standard concept"):
        inspect_athena_snapshot(source, release_id="empty", vocabulary_version="1")


class ScalarSession:
    def __init__(self, existing: object) -> None:
        self.existing = existing

    def scalar(self, _statement: object) -> object:
        return self.existing


def test_load_athena_snapshot_is_idempotent_and_rejects_release_rebinding(tmp_path: Path) -> None:
    source = tmp_path / "athena"
    write_athena_snapshot(source)
    snapshot = inspect_athena_snapshot(source, release_id="athena-test-1", vocabulary_version="1")
    same = SimpleNamespace(source_checksum_sha256=snapshot.source_checksum_sha256)
    different = SimpleNamespace(source_checksum_sha256="0" * 64)

    session = cast(Any, ScalarSession(same))
    assert not load_athena_snapshot(session, source, snapshot, loaded_by="operator")
    with pytest.raises(AthenaImportError, match="different Athena checksum"):
        load_athena_snapshot(
            cast(Session, ScalarSession(different)),
            source,
            snapshot,
            loaded_by="operator",
        )
