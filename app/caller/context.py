"""Build a ``CallerContext`` for a cleared briefing (task 5.1)."""

from uuid import UUID

from sqlalchemy import text

from app.caller.types import CallerContext, StoryRef
from app.db.session import get_engine
from app.standards_desk import ClearedScript

HEARD_CHARS = 600  # per story, enough for the classifier to match a follow-up


async def story_titles(story_ids: list[UUID]) -> dict[UUID, str]:
    if not story_ids:
        return {}
    async with get_engine().connect() as conn:
        rows = await conn.execute(
            text("SELECT id, title FROM stories WHERE id = ANY(:ids)"), {"ids": story_ids}
        )
        return {r.id: r.title for r in rows}


async def context_for(script: ClearedScript, current_story_id: UUID | None = None) -> CallerContext:
    """The briefing's stories in air order (only stories with a cleared line)."""
    order = list(dict.fromkeys(ln.story_id for ln in script.lines))
    titles = await story_titles(order)
    heard = {sid: " ".join(ln.text for ln in script.lines if ln.story_id == sid) for sid in order}
    return CallerContext(
        briefing_id=script.briefing_id,
        stories=tuple(
            StoryRef(sid, titles.get(sid, ""), heard[sid][:HEARD_CHARS]) for sid in order
        ),
        current_story_id=current_story_id,
    )
