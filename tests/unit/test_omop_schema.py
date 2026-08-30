from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import Connection

import ehrfs.omop.schema as schema_module
from ehrfs.omop.schema import (
    InvalidSchemaNameError,
    OmopSchemaChecksumError,
    UnknownOmopAssetError,
    checked_asset,
    statements,
)


class _RecordingConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement: object) -> None:
        self.statements.append(str(statement))


DDL = "OMOPCDM_postgresql_5.4_ddl.sql"


def test_official_omop_assets_are_pinned_and_rendered() -> None:
    ddl = checked_asset(DDL)
    rendered = statements(DDL, schema="omop_test")

    assert ddl.count("CREATE TABLE @cdmDatabaseSchema.") == 39
    assert len(rendered) == 39
    assert all("@cdmDatabaseSchema" not in statement for statement in rendered)
    assert "omop_test.person" in rendered[0]


def test_schema_install_accepts_the_empty_bootstrap_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _RecordingConnection()
    monkeypatch.setattr(schema_module, "INSTALL_ASSETS", ())

    schema_module.install_schema(cast(Connection, connection))

    assert connection.statements == ["CREATE SCHEMA IF NOT EXISTS omop"]


def test_official_omop_assets_reject_unknown_tampered_and_unsafe_inputs(tmp_path: Path) -> None:
    with pytest.raises(UnknownOmopAssetError):
        checked_asset("not-pinned.sql")

    (tmp_path / DDL).write_text("changed", encoding="utf-8")
    with pytest.raises(OmopSchemaChecksumError):
        checked_asset(DDL, asset_root=tmp_path)

    with pytest.raises(InvalidSchemaNameError):
        statements(DDL, schema="omop;drop schema public")
