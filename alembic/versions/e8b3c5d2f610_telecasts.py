"""telecasts: one-story broadcasts requested from the Press feed (task 8.3, decision 0027)

Revision ID: e8b3c5d2f610
Revises: d4e1a7b93c02
Create Date: 2026-11-23 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e8b3c5d2f610"
down_revision: str | Sequence[str] | None = "d4e1a7b93c02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "telecasts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("story_id", sa.Uuid(), nullable=False),
        sa.Column("briefing_id", sa.Uuid(), nullable=True),
        sa.Column("step", sa.String(length=10), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("audio_path", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["briefing_id"], ["briefings.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "step IN ('queued', 'writing', 'checking', 'clearing', 'voicing', 'ready', 'failed')",
            name="ck_telecasts_step",
        ),
    )
    op.create_index("ix_telecasts_story_id", "telecasts", ["story_id"])
    op.create_index("ix_telecasts_briefing_id", "telecasts", ["briefing_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("telecasts")
