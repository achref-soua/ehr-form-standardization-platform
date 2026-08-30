"""Checksummed installation of the upstream OMOP CDM 5.4.2 PostgreSQL schema."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from sqlalchemy import Connection, text

ASSET_ROOT = Path(__file__).resolve().parents[3] / "infra" / "postgres" / "omop54"
ASSET_SHA256 = {
    "OMOPCDM_postgresql_5.4_ddl.sql": (
        "ae99be6e79edfad5f17ef71edda176281b45e3aa9e400e7a9f829103f5ec4771"
    ),
    "OMOPCDM_postgresql_5.4_primary_keys.sql": (
        "ffe6cc10f04a713ea86825dccfc1d8b8a981ba6037fc69cb9df4c80ce2f1970d"
    ),
    "OMOPCDM_postgresql_5.4_indices.sql": (
        "8a3537f971c75e9e33c3d1d13b041d4e5de8532dc1607bc31349af3679a66eec"
    ),
    "OMOPCDM_postgresql_5.4_constraints.sql": (
        "dedae8072ef585e25e0ab2624f557e37e5ddd2d51e75810af58b02e990a4f293"
    ),
}
INSTALL_ASSETS = (
    "OMOPCDM_postgresql_5.4_ddl.sql",
    "OMOPCDM_postgresql_5.4_primary_keys.sql",
    "OMOPCDM_postgresql_5.4_indices.sql",
)
SCHEMA_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
OFFICIAL_TABLE_COUNT = 39


class UnknownOmopAssetError(ValueError):
    """Raised when a caller requests an unpinned schema asset."""


class OmopSchemaChecksumError(RuntimeError):
    """Raised when a vendored upstream asset has changed."""


class InvalidSchemaNameError(ValueError):
    """Raised before interpolating an unsafe PostgreSQL identifier."""


def checked_asset(name: str, *, asset_root: Path = ASSET_ROOT) -> str:
    """Read one known asset and reject local or upstream drift."""
    if name not in ASSET_SHA256:
        raise UnknownOmopAssetError(name)
    payload = (asset_root / name).read_bytes()
    checksum = hashlib.sha256(payload).hexdigest()
    if checksum != ASSET_SHA256[name]:
        raise OmopSchemaChecksumError(name)
    return payload.decode("utf-8")


def statements(asset: str, *, schema: str, asset_root: Path = ASSET_ROOT) -> tuple[str, ...]:
    """Render the upstream placeholder and split its simple SQL script."""
    if not SCHEMA_PATTERN.fullmatch(schema):
        raise InvalidSchemaNameError(schema)
    rendered = checked_asset(asset, asset_root=asset_root).replace("@cdmDatabaseSchema", schema)
    return tuple(statement.strip() for statement in rendered.split(";") if statement.strip())


def install_schema(
    connection: Connection,
    *,
    schema: str = "omop",
    asset_root: Path = ASSET_ROOT,
) -> None:
    """Create all 39 official tables, primary keys, and recommended indices."""
    if not SCHEMA_PATTERN.fullmatch(schema):
        raise InvalidSchemaNameError(schema)
    # The PostgreSQL bootstrap creates the empty schema so it can establish
    # least-privilege defaults before Alembic runs on a fresh volume.
    connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
    for asset in INSTALL_ASSETS:
        for statement in statements(asset, schema=schema, asset_root=asset_root):
            connection.execute(text(statement))


def is_official_schema(connection: Connection, *, schema: str = "omop") -> bool:
    """Return whether the target has the complete 39-table 5.4 shape."""
    if not SCHEMA_PATTERN.fullmatch(schema):
        raise InvalidSchemaNameError(schema)
    table_count = connection.scalar(
        text(
            """
            SELECT count(*)
            FROM information_schema.tables
            WHERE table_schema = :schema AND table_type = 'BASE TABLE'
            """
        ),
        {"schema": schema},
    )
    has_birth_datetime = connection.scalar(
        text(
            """
            SELECT EXISTS (
              SELECT 1 FROM information_schema.columns
              WHERE table_schema = :schema
                AND table_name = 'person'
                AND column_name = 'birth_datetime'
            )
            """
        ),
        {"schema": schema},
    )
    return int(table_count or 0) == OFFICIAL_TABLE_COUNT and bool(has_birth_datetime)
