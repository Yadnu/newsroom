"""claim sources: the sources the Writer cited for each claim (decision 0011)

Revision ID: f41cfce23b88
Revises: f1b85b824a32
Create Date: 2026-11-17 00:12:25.189639

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f41cfce23b88"
down_revision: str | Sequence[str] | None = "f1b85b824a32"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "claim_sources",
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("claim_id", "source_id"),
    )
    op.create_index(
        op.f("ix_claim_sources_source_id"), "claim_sources", ["source_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_claim_sources_source_id"), table_name="claim_sources")
    op.drop_table("claim_sources")
