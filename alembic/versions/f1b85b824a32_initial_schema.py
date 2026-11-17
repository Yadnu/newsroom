"""initial schema

Revision ID: f1b85b824a32
Revises:
Create Date: 2026-11-16 23:06:58.859477

"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1b85b824a32"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "briefings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("target_minutes", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("outlet", sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("trust_score", sa.Float(), nullable=False),
        sa.Column("retracted", sa.Boolean(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=1024), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_hash"),
        sa.UniqueConstraint("url"),
    )
    op.create_index(
        "ix_sources_embedding_hnsw",
        "sources",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_table(
        "stories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("centroid", pgvector.sqlalchemy.vector.VECTOR(dim=1024), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_stories_centroid_hnsw",
        "stories",
        ["centroid"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"centroid": "vector_cosine_ops"},
    )
    op.create_table(
        "script_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("briefing_id", sa.Uuid(), nullable=False),
        sa.Column("story_id", sa.Uuid(), nullable=True),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("audio_start_ms", sa.Integer(), nullable=True),
        sa.Column("audio_end_ms", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["briefing_id"], ["briefings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("briefing_id", "order"),
    )
    op.create_index(
        op.f("ix_script_lines_briefing_id"), "script_lines", ["briefing_id"], unique=False
    )
    op.create_index(op.f("ix_script_lines_story_id"), "script_lines", ["story_id"], unique=False)
    op.create_table(
        "story_sources",
        sa.Column("story_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("story_id", "source_id"),
    )
    op.create_table(
        "traces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("briefing_id", sa.Uuid(), nullable=True),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("component", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
        sa.Column("event", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["briefing_id"], ["briefings.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_traces_briefing_id"), "traces", ["briefing_id"], unique=False)
    op.create_index(
        "ix_traces_component_started_at", "traces", ["component", "started_at"], unique=False
    )
    op.create_table(
        "claims",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("script_line_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("verdict", sa.String(length=20), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("rewrite_round", sa.Integer(), nullable=False),
        sa.Column("judged_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["script_line_id"], ["script_lines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_claims_script_line_id"), "claims", ["script_line_id"], unique=False)
    op.create_index(op.f("ix_claims_verdict"), "claims", ["verdict"], unique=False)
    op.create_table(
        "claim_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("passage", sa.Text(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_claim_evidence_claim_id"), "claim_evidence", ["claim_id"], unique=False
    )
    op.create_index(
        op.f("ix_claim_evidence_source_id"), "claim_evidence", ["source_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_claim_evidence_source_id"), table_name="claim_evidence")
    op.drop_index(op.f("ix_claim_evidence_claim_id"), table_name="claim_evidence")
    op.drop_table("claim_evidence")
    op.drop_index(op.f("ix_claims_verdict"), table_name="claims")
    op.drop_index(op.f("ix_claims_script_line_id"), table_name="claims")
    op.drop_table("claims")
    op.drop_index("ix_traces_component_started_at", table_name="traces")
    op.drop_index(op.f("ix_traces_briefing_id"), table_name="traces")
    op.drop_table("traces")
    op.drop_table("story_sources")
    op.drop_index(op.f("ix_script_lines_story_id"), table_name="script_lines")
    op.drop_index(op.f("ix_script_lines_briefing_id"), table_name="script_lines")
    op.drop_table("script_lines")
    op.drop_index(
        "ix_stories_centroid_hnsw",
        table_name="stories",
        postgresql_using="hnsw",
        postgresql_ops={"centroid": "vector_cosine_ops"},
    )
    op.drop_table("stories")
    op.drop_index(
        "ix_sources_embedding_hnsw",
        table_name="sources",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_table("sources")
    op.drop_table("briefings")
    # The vector extension is left in place; other databases objects may use it.
