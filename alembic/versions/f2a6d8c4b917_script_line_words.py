"""script_lines.audio_words: per-word audio timings from the TTS (task 8.4)

Revision ID: f2a6d8c4b917
Revises: e8b3c5d2f610
Create Date: 2026-11-23 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2a6d8c4b917"
down_revision: str | Sequence[str] | None = "e8b3c5d2f610"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "script_lines",
        sa.Column("audio_words", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("script_lines", "audio_words")
