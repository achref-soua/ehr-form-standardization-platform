"""Create control/audit schemas and the official OMOP 5.4.2 schema."""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

from ehrfs.omop.schema import install_schema
from ehrfs.storage.tables import Base

revision = "20260829_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    for schema in ("control", "audit"):
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
    install_schema(connection)
    application_tables = tuple(
        table for table in Base.metadata.tables.values() if table.schema != "omop"
    )
    Base.metadata.create_all(connection, tables=application_tables)


def downgrade() -> None:
    connection = op.get_bind()
    application_tables = tuple(
        table for table in Base.metadata.tables.values() if table.schema != "omop"
    )
    Base.metadata.drop_all(connection, tables=application_tables)
    for schema in ("omop", "audit", "control"):
        connection.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
