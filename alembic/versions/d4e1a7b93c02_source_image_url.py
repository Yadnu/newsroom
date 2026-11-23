"""sources.image_url: the feed's thumbnail for the Press feed (task 8.2)

Revision ID: d4e1a7b93c02
Revises: c7d2e8f40a61
Create Date: 2026-11-23 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e1a7b93c02"
down_revision: str | Sequence[str] | None = "c7d2e8f40a61"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("sources", sa.Column("image_url", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("sources", "image_url")
