"""Clear a briefing that is already in the database (the Anchor's entry point, task 4.2)."""

from uuid import UUID

from sqlalchemy import text

from app.db.session import get_engine
from app.editor import ReviewedScript
from app.standards_desk.clear import clear_for_air
from app.standards_desk.types import ClearedScript
from app.writer import DraftClaim, DraftLine, Script


class BriefingNotFoundError(LookupError):
    """No briefing with that id."""


async def load_script(briefing_id: UUID) -> Script:
    """The stored script: lines in order, each with its current claims and cited sources."""
    async with get_engine().connect() as conn:
        if (
            await conn.execute(text("SELECT 1 FROM briefings WHERE id = :b"), {"b": briefing_id})
        ).first() is None:
            raise BriefingNotFoundError(f"no briefing {briefing_id}")
        lines = (
            await conn.execute(
                text(
                    'SELECT id, story_id, "order", text, kind FROM script_lines'
                    " WHERE briefing_id = :b AND kind IN ('script', 'correction')"
                    ' ORDER BY "order"'
                ),
                {"b": briefing_id},
            )
        ).all()
        claims: dict[UUID, list[DraftClaim]] = {}
        if lines:
            rows = await conn.execute(
                text(
                    "SELECT c.id, c.script_line_id, c.text,"
                    " coalesce(array_agg(cs.source_id) FILTER (WHERE cs.source_id IS NOT NULL),"
                    " '{}') AS sources"
                    " FROM claims c LEFT JOIN claim_sources cs ON cs.claim_id = c.id"
                    " WHERE c.script_line_id = ANY(:ids) GROUP BY c.id ORDER BY c.id"
                ),
                {"ids": [ln.id for ln in lines]},
            )
            for r in rows:
                claims.setdefault(r.script_line_id, []).append(
                    DraftClaim(id=r.id, text=r.text, source_ids=list(r.sources))
                )
    return Script(
        briefing_id=briefing_id,
        lines=[
            DraftLine(
                id=ln.id,
                story_id=ln.story_id,
                order=ln.order,
                text=ln.text,
                claims=claims.get(ln.id, []),
                kind=ln.kind,
            )
            for ln in lines
            if ln.story_id is not None
        ],
    )


async def clear_stored(briefing_id: UUID) -> ClearedScript:
    """Re-run ``clear_for_air`` on a stored briefing. Raises ``BriefingNotFoundError`` or
    ``NotClearedError``."""
    script = await load_script(briefing_id)
    return await clear_for_air(ReviewedScript(script=script, verdicts=[], rounds=0))
