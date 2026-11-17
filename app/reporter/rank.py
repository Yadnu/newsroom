"""Today's top stories: corroborated by several outlets, then by many sources, then fresh.

Only non-retracted sources count. This is the Reporter's view; the Producer's rundown (task 2.0)
builds on it.
"""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, select

from app.archive import span
from app.db.models import Source, Story, StorySource, utcnow
from app.db.session import get_engine

_sources = Source.__table__  # type: ignore[attr-defined]
_stories = Story.__table__  # type: ignore[attr-defined]
_links = StorySource.__table__  # type: ignore[attr-defined]


class StorySourceRef(BaseModel):
    outlet: str
    title: str
    url: str
    published_at: datetime | None


class TopStory(BaseModel):
    id: UUID
    title: str
    n_sources: int
    outlets: list[str]
    latest_at: datetime
    sources: list[StorySourceRef]


async def top_stories(
    limit: int = 10, window_hours: int = 24, min_sources: int = 2
) -> list[TopStory]:
    since = utcnow() - timedelta(hours=window_hours)
    seen_at = func.coalesce(_sources.c.published_at, _sources.c.fetched_at)
    n_sources = func.count(_sources.c.id)
    n_outlets = func.count(func.distinct(_sources.c.outlet))
    latest = func.max(seen_at)
    ranked = (
        select(
            _stories.c.id,
            _stories.c.title,
            n_sources.label("n_sources"),
            latest.label("latest_at"),
        )
        .join(_links, _links.c.story_id == _stories.c.id)
        .join(_sources, _sources.c.id == _links.c.source_id)
        .where(_sources.c.retracted.is_(False))
        .group_by(_stories.c.id, _stories.c.title)
        .having(latest >= since, n_sources >= min_sources)
        .order_by(n_outlets.desc(), n_sources.desc(), latest.desc(), _stories.c.id)
        .limit(limit)
    )
    with span("reporter", "top_stories", limit=limit, window_hours=window_hours) as s:
        async with get_engine().connect() as conn:
            rows = (await conn.execute(ranked)).all()
            ids = [r.id for r in rows]
            members: list[Any] = []
            if ids:
                members_q = (
                    select(
                        _links.c.story_id,
                        _sources.c.outlet,
                        _sources.c.title,
                        _sources.c.url,
                        _sources.c.published_at,
                    )
                    .join(_sources, _sources.c.id == _links.c.source_id)
                    .where(_links.c.story_id.in_(ids), _sources.c.retracted.is_(False))
                    .order_by(seen_at.desc())
                )
                members = list((await conn.execute(members_q)).all())
        by_story: dict[UUID, list[StorySourceRef]] = {i: [] for i in ids}
        for m in members:
            by_story[m.story_id].append(
                StorySourceRef(
                    outlet=m.outlet, title=m.title, url=m.url, published_at=m.published_at
                )
            )
        result = [
            TopStory(
                id=r.id,
                title=r.title,
                n_sources=int(r.n_sources),
                outlets=sorted({ref.outlet for ref in by_story[r.id]}),
                latest_at=r.latest_at,
                sources=by_story[r.id],
            )
            for r in rows
        ]
        s.set(returned=len(result))
    return result
