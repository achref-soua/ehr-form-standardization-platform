"""Record immutable Athena vocabulary imports."""

from __future__ import annotations

from alembic import op

from ehrfs.storage.tables import VocabularyImportRow

revision = "20260829_0005"
down_revision = "20260829_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    VocabularyImportRow.__table__.create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    VocabularyImportRow.__table__.drop(op.get_bind(), checkfirst=True)
