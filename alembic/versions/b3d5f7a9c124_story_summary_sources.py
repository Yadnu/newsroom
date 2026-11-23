"""stories.summary_sources: live sources a summary was written from (task 9.2)

Revision ID: b3d5f7a9c124
Revises: a7c1e4f9d203
Create Date: 2026-11-23 19:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3d5f7a9c124"
down_revision: str | Sequence[str] | None = "a7c1e4f9d203"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("stories", sa.Column("summary_sources", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("stories", "summary_sources")
