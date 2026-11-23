"""SQLModel tables. The trace chain: sources -> stories -> script_lines -> claims -> claim_evidence.
Claims also record the sources the Writer cited in ``claim_sources``.

Delete rules keep the chain intact: deleting a briefing removes its lines, claims, and evidence;
a source cannot be deleted while evidence points at it (retract it with ``retracted`` instead).
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

EMBEDDING_DIM = 1024  # decision 0007: voyage-4-lite at 1024 dims. Changing it needs a migration.


def utcnow() -> datetime:
    return datetime.now(UTC)


def _ts() -> Any:
    return Field(default_factory=utcnow, sa_type=DateTime(timezone=True), nullable=False)


def _ts_opt() -> Any:
    return Field(default=None, sa_type=DateTime(timezone=True), nullable=True)


def _fk(target: str, ondelete: str, *, nullable: bool = False, index: bool = True) -> Any:
    return Field(
        sa_column=Column(ForeignKey(target, ondelete=ondelete), nullable=nullable, index=index)
    )


def _vector(*, nullable: bool = True) -> Any:
    return Field(default=None, sa_column=Column(Vector(EMBEDDING_DIM), nullable=nullable))


class Verdict(StrEnum):
    pending = "pending"
    approved = "approved"
    rewrite = "rewrite"
    rejected = "rejected"


class BriefingStatus(StrEnum):
    draft = "draft"
    judged = "judged"
    cleared = "cleared"
    aired = "aired"
    failed = "failed"


class Source(SQLModel, table=True):
    __tablename__ = "sources"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    url: str = Field(sa_column=Column(Text, nullable=False, unique=True))
    outlet: str = Field(max_length=200)
    title: str = Field(sa_type=Text)
    published_at: datetime | None = _ts_opt()
    fetched_at: datetime = _ts()
    content: str = Field(sa_type=Text)
    content_hash: str = Field(sa_column=Column(String(64), nullable=False, unique=True))
    trust_score: float = Field(default=0.5, ge=0.0, le=1.0)
    retracted: bool = False
    retracted_at: datetime | None = _ts_opt()  # task 6.2, decision 0023
    retraction_reason: str | None = Field(default=None, sa_type=Text)
    image_url: str | None = Field(default=None, sa_type=Text)  # feed thumbnail (task 8.2)
    embedding: list[float] | None = _vector()


class Story(SQLModel, table=True):
    __tablename__ = "stories"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    title: str = Field(sa_type=Text)
    summary: str | None = Field(default=None, sa_type=Text)
    created_at: datetime = _ts()
    centroid: list[float] | None = _vector()


class StorySource(SQLModel, table=True):
    __tablename__ = "story_sources"

    story_id: UUID = Field(
        sa_column=Column(ForeignKey("stories.id", ondelete="CASCADE"), primary_key=True)
    )
    source_id: UUID = Field(
        sa_column=Column(ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True)
    )


class Briefing(SQLModel, table=True):
    __tablename__ = "briefings"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    created_at: datetime = _ts()
    status: BriefingStatus = Field(default=BriefingStatus.draft, sa_type=String(20))
    target_minutes: float = Field(gt=0)


class ScriptLine(SQLModel, table=True):
    __tablename__ = "script_lines"
    __table_args__ = (
        UniqueConstraint("briefing_id", "order"),
        CheckConstraint("kind IN ('script', 'answer', 'correction')", name="ck_script_lines_kind"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    briefing_id: UUID = _fk("briefings.id", "CASCADE")
    story_id: UUID | None = _fk("stories.id", "SET NULL", nullable=True)
    order: int  # correction lines take negative orders so they air first (decision 0023)
    text: str = Field(sa_type=Text)
    audio_start_ms: int | None = None
    audio_end_ms: int | None = None
    # "script" (the briefing), "answer" (spoken reply to a listener question, decision 0020) or
    # "correction" (an on-air correction of an earlier briefing, decision 0023)
    kind: str = Field(
        default="script",
        sa_column=Column(String(10), nullable=False, server_default="script"),
    )
    question: str | None = Field(default=None, sa_type=Text)  # what an answer line replies to


class Claim(SQLModel, table=True):
    __tablename__ = "claims"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    script_line_id: UUID = _fk("script_lines.id", "CASCADE")
    text: str = Field(sa_type=Text)
    verdict: Verdict = Field(default=Verdict.pending, sa_type=String(20), index=True)
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    reason: str | None = Field(default=None, sa_type=Text)
    rewrite_round: int = Field(default=0, ge=0)
    judged_at: datetime | None = _ts_opt()


class ClaimEvidence(SQLModel, table=True):
    __tablename__ = "claim_evidence"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    claim_id: UUID = _fk("claims.id", "CASCADE")
    source_id: UUID = _fk("sources.id", "RESTRICT")
    passage: str = Field(sa_type=Text)
    score: float | None = Field(default=None, ge=0.0, le=1.0)


class ClaimSource(SQLModel, table=True):
    """Sources the Writer cited for a claim (decision 0011). Not evidence: the Editor's verified
    passages live in ``claim_evidence``, and only those can approve a claim."""

    __tablename__ = "claim_sources"

    claim_id: UUID = Field(
        sa_column=Column(ForeignKey("claims.id", ondelete="CASCADE"), primary_key=True)
    )
    source_id: UUID = Field(
        sa_column=Column(
            ForeignKey("sources.id", ondelete="RESTRICT"), primary_key=True, index=True
        )
    )


class Correction(SQLModel, table=True):
    """A claim affected by a source retraction (task 6.2, decision 0023). ``orphaned``: no evidence
    from a live source is left; ``weakened``: other live evidence remains. ``on_air``: the briefing
    aired with the claim approved, so the next briefing must correct it (``correction_line_id``)."""

    __tablename__ = "corrections"
    __table_args__ = (
        UniqueConstraint("source_id", "claim_id"),
        CheckConstraint("impact IN ('orphaned', 'weakened')", name="ck_corrections_impact"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    source_id: UUID = _fk("sources.id", "RESTRICT")
    briefing_id: UUID = _fk("briefings.id", "CASCADE")
    script_line_id: UUID = _fk("script_lines.id", "CASCADE")
    claim_id: UUID | None = _fk("claims.id", "SET NULL", nullable=True, index=False)
    claim_text: str = Field(sa_type=Text)
    impact: str = Field(sa_type=String(10))
    on_air: bool = False
    correction_line_id: UUID | None = _fk("script_lines.id", "SET NULL", nullable=True, index=False)
    created_at: datetime = _ts()


class Trace(SQLModel, table=True):
    __tablename__ = "traces"
    __table_args__ = (Index("ix_traces_component_started_at", "component", "started_at"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    briefing_id: UUID | None = _fk("briefings.id", "SET NULL", nullable=True)
    parent_id: UUID | None = Field(default=None)
    component: str = Field(max_length=50)
    event: str = Field(max_length=100)
    started_at: datetime = _ts()
    latency_ms: float | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    error: str | None = Field(default=None, sa_type=Text)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))


HNSW_INDEXES = (
    Index(
        "ix_sources_embedding_hnsw",
        Source.__table__.c.embedding,  # type: ignore[attr-defined]
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    ),
    Index(
        "ix_stories_centroid_hnsw",
        Story.__table__.c.centroid,  # type: ignore[attr-defined]
        postgresql_using="hnsw",
        postgresql_ops={"centroid": "vector_cosine_ops"},
    ),
)
