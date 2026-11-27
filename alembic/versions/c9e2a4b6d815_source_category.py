"""sources.category: the feed's category, for the Press filter (task 9.5)

Revision ID: c9e2a4b6d815
Revises: b3d5f7a9c124
Create Date: 2026-11-23 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9e2a4b6d815"
down_revision: str | Sequence[str] | None = "b3d5f7a9c124"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("sources", sa.Column("category", sa.String(length=30), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("sources", "category")
