"""script line kind: answers to listener questions are script lines of kind 'answer' (decision 0020)

Revision ID: a3c9e5d71b20
Revises: f41cfce23b88
Create Date: 2026-11-19 16:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3c9e5d71b20"
down_revision: str | Sequence[str] | None = "f41cfce23b88"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "script_lines",
        sa.Column("kind", sa.String(length=10), nullable=False, server_default="script"),
    )
    op.add_column("script_lines", sa.Column("question", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_script_lines_kind", "script_lines", "kind IN ('script', 'answer')"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_script_lines_kind", "script_lines", type_="check")
    op.drop_column("script_lines", "question")
    op.drop_column("script_lines", "kind")
