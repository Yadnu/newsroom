"""Data model: SQLModel tables and Alembic migrations.

Node: context/nodes/data-model.md
"""

from app.db.models import (
    EMBEDDING_DIM,
    Briefing,
    BriefingStatus,
    Claim,
    ClaimEvidence,
    ClaimSource,
    Correction,
    ScriptLine,
    Source,
    Story,
    StorySource,
    Telecast,
    Trace,
    Verdict,
)
from app.db.session import get_engine, session_scope

__all__ = [
    "EMBEDDING_DIM",
    "Briefing",
    "BriefingStatus",
    "Claim",
    "ClaimEvidence",
    "ClaimSource",
    "Correction",
    "ScriptLine",
    "Source",
    "Story",
    "StorySource",
    "Telecast",
    "Trace",
    "Verdict",
    "get_engine",
    "session_scope",
]
