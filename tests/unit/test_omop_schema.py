from __future__ import annotations

from pathlib import Path

import pytest

from ehrfs.omop.schema import (
    InvalidSchemaNameError,
    OmopSchemaChecksumError,
    UnknownOmopAssetError,
    checked_asset,
    statements,
)

DDL = "OMOPCDM_postgresql_5.4_ddl.sql"


def test_official_omop_assets_are_pinned_and_rendered() -> None:
    ddl = checked_asset(DDL)
    rendered = statements(DDL, schema="omop_test")

    assert ddl.count("CREATE TABLE @cdmDatabaseSchema.") == 39
    assert len(rendered) == 39
    assert all("@cdmDatabaseSchema" not in statement for statement in rendered)
    assert "omop_test.person" in rendered[0]


def test_official_omop_assets_reject_unknown_tampered_and_unsafe_inputs(tmp_path: Path) -> None:
    with pytest.raises(UnknownOmopAssetError):
        checked_asset("not-pinned.sql")

    (tmp_path / DDL).write_text("changed", encoding="utf-8")
    with pytest.raises(OmopSchemaChecksumError):
        checked_asset(DDL, asset_root=tmp_path)

    with pytest.raises(InvalidSchemaNameError):
        statements(DDL, schema="omop;drop schema public")
