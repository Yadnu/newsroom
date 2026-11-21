"""corrections: source retraction columns, the corrections table, correction script lines
(task 6.2, decision 0023)

Revision ID: c7d2e8f40a61
Revises: a3c9e5d71b20
Create Date: 2026-11-21 00:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7d2e8f40a61"
down_revision: str | Sequence[str] | None = "a3c9e5d71b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("sources", sa.Column("retracted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sources", sa.Column("retraction_reason", sa.Text(), nullable=True))
    op.drop_constraint("ck_script_lines_kind", "script_lines", type_="check")
    op.create_check_constraint(
        "ck_script_lines_kind", "script_lines", "kind IN ('script', 'answer', 'correction')"
    )
    op.create_table(
        "corrections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("briefing_id", sa.Uuid(), nullable=False),
        sa.Column("script_line_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=True),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("impact", sa.String(length=10), nullable=False),
        sa.Column("on_air", sa.Boolean(), nullable=False),
        sa.Column("correction_line_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["briefing_id"], ["briefings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["script_line_id"], ["script_lines.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["correction_line_id"], ["script_lines.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "claim_id"),
        sa.CheckConstraint("impact IN ('orphaned', 'weakened')", name="ck_corrections_impact"),
    )
    op.create_index("ix_corrections_source_id", "corrections", ["source_id"])
    op.create_index("ix_corrections_briefing_id", "corrections", ["briefing_id"])
    op.create_index("ix_corrections_script_line_id", "corrections", ["script_line_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("corrections")
    op.execute("DELETE FROM script_lines WHERE kind = 'correction'")
    op.drop_constraint("ck_script_lines_kind", "script_lines", type_="check")
    op.create_check_constraint(
        "ck_script_lines_kind", "script_lines", "kind IN ('script', 'answer')"
    )
    op.drop_column("sources", "retraction_reason")
    op.drop_column("sources", "retracted_at")
