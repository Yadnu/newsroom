"""telecasts.step may be 'expired' (audio removed after retention, task 9.1)

Revision ID: a7c1e4f9d203
Revises: f2a6d8c4b917
Create Date: 2026-11-23 18:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c1e4f9d203"
down_revision: str | Sequence[str] | None = "f2a6d8c4b917"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "step IN ('queued', 'writing', 'checking', 'clearing', 'voicing', 'ready', 'failed')"
NEW = (
    "step IN ('queued', 'writing', 'checking', 'clearing', 'voicing', 'ready', 'failed', 'expired')"
)


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint("ck_telecasts_step", "telecasts", type_="check")
    op.create_check_constraint("ck_telecasts_step", "telecasts", NEW)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("UPDATE telecasts SET step = 'failed' WHERE step = 'expired'")
    op.drop_constraint("ck_telecasts_step", "telecasts", type_="check")
    op.create_check_constraint("ck_telecasts_step", "telecasts", OLD)
