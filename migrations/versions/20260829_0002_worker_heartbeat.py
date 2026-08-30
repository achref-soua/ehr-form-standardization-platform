"""Add durable worker availability heartbeat."""

from __future__ import annotations

from alembic import op

from ehrfs.storage.tables import WorkerHeartbeatRow

revision = "20260829_0002"
down_revision = "20260829_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    WorkerHeartbeatRow.__table__.create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    WorkerHeartbeatRow.__table__.drop(op.get_bind(), checkfirst=True)
