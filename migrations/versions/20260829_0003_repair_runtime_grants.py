"""Repair runtime grants for databases upgraded from the bootstrap schema."""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "20260829_0003"
down_revision = "20260829_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        text(
            """
            DO $$
            BEGIN
              IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'ehrfs_app') THEN
                GRANT USAGE ON SCHEMA control, audit, omop TO ehrfs_app;
                GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA control TO ehrfs_app;
                GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA audit TO ehrfs_app;
                GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA omop TO ehrfs_app;
                GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA control, audit, omop TO ehrfs_app;
              END IF;

              IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'ehrfs_worker') THEN
                GRANT USAGE ON SCHEMA control, audit, omop TO ehrfs_worker;
                GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES
                  IN SCHEMA control TO ehrfs_worker;
                GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA audit TO ehrfs_worker;
                GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA omop TO ehrfs_worker;
                GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA control, audit, omop TO ehrfs_worker;
              END IF;

              IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'ehrfs_readonly') THEN
                GRANT USAGE ON SCHEMA control, audit, omop TO ehrfs_readonly;
                GRANT SELECT ON ALL TABLES IN SCHEMA control, audit, omop TO ehrfs_readonly;
              END IF;
            END
            $$;
            """
        )
    )
    connection.execute(
        text(
            """
            DO $$
            BEGIN
              IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'ehrfs_app') THEN
                ALTER DEFAULT PRIVILEGES IN SCHEMA control, omop
                  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ehrfs_app;
                ALTER DEFAULT PRIVILEGES IN SCHEMA audit
                  GRANT SELECT, INSERT ON TABLES TO ehrfs_app;
                ALTER DEFAULT PRIVILEGES IN SCHEMA control, audit, omop
                  GRANT USAGE, SELECT ON SEQUENCES TO ehrfs_app;
              END IF;
              IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'ehrfs_worker') THEN
                ALTER DEFAULT PRIVILEGES IN SCHEMA control, omop
                  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ehrfs_worker;
                ALTER DEFAULT PRIVILEGES IN SCHEMA audit
                  GRANT SELECT, INSERT ON TABLES TO ehrfs_worker;
                ALTER DEFAULT PRIVILEGES IN SCHEMA control, audit, omop
                  GRANT USAGE, SELECT ON SEQUENCES TO ehrfs_worker;
              END IF;
              IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'ehrfs_readonly') THEN
                ALTER DEFAULT PRIVILEGES IN SCHEMA control, audit, omop
                  GRANT SELECT ON TABLES TO ehrfs_readonly;
              END IF;
            END
            $$;
            """
        )
    )


def downgrade() -> None:
    # Runtime access existed before this repair migration and is intentionally
    # retained when downgrading; revoking it would make the application unusable.
    pass
