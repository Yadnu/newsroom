"""Corrections read API (task 6.2, decision 0023): claims affected by a source retraction."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.archive.span import span
from app.db.session import get_engine


class CorrectionRef(BaseModel):
    id: UUID
    created_at: datetime
    briefing_id: UUID
    line_id: UUID
    line_text: str
    claim_id: UUID | None
    claim_text: str
    impact: str  # "orphaned": no live evidence left; "weakened": other live evidence remains
    on_air: bool  # the briefing aired with this claim, so a correction line is due
    source_id: UUID
    outlet: str
    url: str
    reason: str | None
    retracted_at: datetime | None
    correction_line_id: UUID | None  # the queued on-air correction, once a briefing carries it
    correction_briefing_id: UUID | None


_SQL = """
SELECT c.id, c.created_at, c.briefing_id, c.script_line_id AS line_id, l.text AS line_text,
  c.claim_id, c.claim_text, c.impact, c.on_air, c.source_id, s.outlet, s.url,
  s.retraction_reason AS reason, s.retracted_at, c.correction_line_id,
  cl.briefing_id AS correction_briefing_id
FROM corrections c
JOIN script_lines l ON l.id = c.script_line_id
JOIN sources s ON s.id = c.source_id
LEFT JOIN script_lines cl ON cl.id = c.correction_line_id
"""


async def corrections_for(
    conn: AsyncConnection, briefing_id: UUID | None, limit: int
) -> list[CorrectionRef]:
    where, params = ("WHERE c.briefing_id = :b", {"b": briefing_id}) if briefing_id else ("", {})
    rows = await conn.execute(
        text(f"{_SQL} {where} ORDER BY c.created_at DESC LIMIT :n"), params | {"n": limit}
    )
    return [CorrectionRef.model_validate(dict(r._mapping)) for r in rows]


async def list_corrections(
    briefing_id: UUID | None = None, limit: int = 100
) -> list[CorrectionRef]:
    """Newest first; optionally only one briefing's."""
    with span("archive", "list_corrections", briefing=briefing_id, limit=limit) as s:
        async with get_engine().connect() as conn:
            out = await corrections_for(conn, briefing_id, limit)
        s.set(rows=len(out))
    return out
