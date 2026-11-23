"""``press_stories()``: the Press feed, newest stories first, cursor-paged (task 8.2).

A story appears once it has at least ``min_sources`` live (non-retracted) sources. Its time is its
newest source's ``published_at`` (or ``fetched_at``), its image the newest source's feed thumbnail.
Summaries are crawler summaries (``Story.summary``), not fact-checked.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select

from app.archive import span
from app.db.models import Source, Story, StorySource, Telecast
from app.db.session import get_engine

MAX_SOURCES_PER_STORY = 8

_stories = Story.__table__  # type: ignore[attr-defined]
_sources = Source.__table__  # type: ignore[attr-defined]
_links = StorySource.__table__  # type: ignore[attr-defined]
_telecasts = Telecast.__table__  # type: ignore[attr-defined]


class PressSource(BaseModel):
    id: UUID
    outlet: str
    title: str
    url: str
    published_at: datetime | None


class TelecastRef(BaseModel):
    """The story's latest telecast (task 8.3)."""

    id: UUID
    step: str


class PressStory(BaseModel):
    id: UUID
    title: str
    summary: str | None  # crawler summary, not fact-checked; None until the worker writes one
    image_url: str | None  # publisher thumbnail from the feed, credited to ``image_outlet``
    image_outlet: str | None
    outlets: list[str]
    n_sources: int
    latest_at: datetime
    sources: list[PressSource]
    telecast: TelecastRef | None = None


class PressCursor(BaseModel):
    """Keyset cursor: the last story of the previous page (feeds often share timestamps)."""

    latest_at: datetime
    id: UUID


async def press_stories(
    limit: int = 20,
    after: PressCursor | None = None,
    min_sources: int = 2,
    story_id: UUID | None = None,
) -> list[PressStory]:
    """Up to ``limit`` stories, newest first, starting after the ``after`` cursor."""
    seen_at = func.coalesce(_sources.c.published_at, _sources.c.fetched_at)
    latest = func.max(seen_at)
    n_sources = func.count(_sources.c.id)
    query = (
        select(_stories.c.id, _stories.c.title, _stories.c.summary, latest.label("latest_at"))
        .join(_links, _links.c.story_id == _stories.c.id)
        .join(_sources, _sources.c.id == _links.c.source_id)
        .where(_sources.c.retracted.is_(False))
        .group_by(_stories.c.id, _stories.c.title, _stories.c.summary)
        .having(n_sources >= min_sources)
        .order_by(latest.desc(), _stories.c.id)
        .limit(limit)
    )
    if story_id is not None:
        query = query.where(_stories.c.id == story_id)
    if after is not None:
        query = query.having(
            or_(latest < after.latest_at, and_(latest == after.latest_at, _stories.c.id > after.id))
        )
    with span("press", "press_stories", limit=limit, after=after and after.model_dump()) as s:
        async with get_engine().connect() as conn:
            rows = (await conn.execute(query)).all()
            ids = [r.id for r in rows]
            members: list[Any] = []
            if ids:
                members_q = (
                    select(
                        _links.c.story_id,
                        _sources.c.id,
                        _sources.c.outlet,
                        _sources.c.title,
                        _sources.c.url,
                        _sources.c.published_at,
                        _sources.c.image_url,
                    )
                    .join(_sources, _sources.c.id == _links.c.source_id)
                    .where(_links.c.story_id.in_(ids), _sources.c.retracted.is_(False))
                    .order_by(seen_at.desc(), _sources.c.id)
                )
                members = list((await conn.execute(members_q)).all())
            telecasts: dict[UUID, TelecastRef] = {}
            if ids:
                newest = (
                    select(_telecasts.c.story_id, _telecasts.c.id, _telecasts.c.step)
                    .where(_telecasts.c.story_id.in_(ids))
                    .order_by(_telecasts.c.story_id, _telecasts.c.created_at.desc())
                    .distinct(_telecasts.c.story_id)
                )
                for t in (await conn.execute(newest)).all():
                    telecasts[t.story_id] = TelecastRef(id=t.id, step=t.step)
        result = [
            _story(r, [m for m in members if m.story_id == r.id], telecasts.get(r.id)) for r in rows
        ]
        s.set(returned=len(result))
    return result


async def press_story(story_id: UUID, min_sources: int = 2) -> PressStory | None:
    """One story as the feed shows it, or None if unknown or below ``min_sources``."""
    found = await press_stories(limit=1, min_sources=min_sources, story_id=story_id)
    return found[0] if found else None


def _story(row: Any, members: list[Any], telecast: TelecastRef | None = None) -> PressStory:
    image = next((m for m in members if m.image_url), None)
    return PressStory(
        id=row.id,
        title=row.title,
        summary=row.summary,
        image_url=image.image_url if image else None,
        image_outlet=image.outlet if image else None,
        outlets=sorted({m.outlet for m in members}),
        n_sources=len(members),
        latest_at=row.latest_at,
        sources=[
            PressSource(
                id=m.id, outlet=m.outlet, title=m.title, url=m.url, published_at=m.published_at
            )
            for m in members[:MAX_SOURCES_PER_STORY]
        ],
        telecast=telecast,
    )
