"""SQLAlchemy engine and transaction management."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import Engine, text
from sqlalchemy import create_engine as sqlalchemy_create_engine
from sqlalchemy.orm import Session, sessionmaker

from ehrfs.config import Settings
from ehrfs.omop.schema import install_schema, is_official_schema
from ehrfs.storage.tables import Base


def create_engine(settings: Settings) -> Engine:
    connect_args: dict[str, str] = {}
    if settings.database_url.startswith("postgresql"):
        connect_args["sslmode"] = settings.database_sslmode
    return sqlalchemy_create_engine(
        settings.database_url,
        connect_args=connect_args,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )


def create_schema(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS control"))
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS audit"))
        schema_exists = bool(connection.scalar(text("SELECT to_regnamespace('omop') IS NOT NULL")))
        if not schema_exists:
            install_schema(connection)
        elif not is_official_schema(connection):
            msg = "partial OMOP schema found; run the Alembic migrations before starting"
            raise RuntimeError(msg)
        application_tables = tuple(
            table for table in Base.metadata.tables.values() if table.schema != "omop"
        )
        Base.metadata.create_all(connection, tables=application_tables)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
