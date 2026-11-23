"""Simple rundown (task 2.0): the top fresh stories, airtime split evenly.

Order follows the Reporter's ranking (most outlets first). Creates the ``briefings`` row so every
later step (Writer, Editor, Anchor) can trace against one ``briefing_id``.
"""

from collections.abc import Sequence
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.archive import span
from app.config import get_settings
from app.db.models import Briefing, BriefingStatus, Source, Story, StorySource
from app.db.session import get_engine, session_scope
from app.reporter.rank import StorySourceRef, TopStory, top_stories

# Fetch this many candidates so topic filtering still leaves enough to choose from.
CANDIDATE_POOL = 100


class NoStoriesError(Exception):
    """No fresh story matched; no briefing was created."""


class RundownItem(BaseModel):
    story_id: UUID
    order: int = Field(ge=0)
    target_seconds: int = Field(ge=1)
    title: str
    sources: list[StorySourceRef]


class Rundown(BaseModel):
    briefing_id: UUID
    minutes: float
    items: list[RundownItem]

    @property
    def total_seconds(self) -> int:
        return sum(i.target_seconds for i in self.items)


def story_count(minutes: float, seconds_per_story: int) -> int:
    return max(1, round(minutes * 60 / seconds_per_story))


def split_evenly(total_seconds: int, n: int) -> list[int]:
    """Whole seconds per item, summing exactly to ``total_seconds``; earlier items get the extra."""
    if n <= 0:
        return []
    base, extra = divmod(total_seconds, n)
    if base == 0:
        raise ValueError(f"{total_seconds}s is too short for {n} stories")
    return [base + (1 if i < extra else 0) for i in range(n)]


def matches_topics(story: TopStory, topics: Sequence[str]) -> bool:
    text = " ".join([story.title, *(s.title for s in story.sources)]).lower()
    return any(t.strip().lower() in text for t in topics if t.strip())


async def build_rundown(minutes: float, topics: list[str] | None = None) -> Rundown:
    if minutes <= 0:
        raise ValueError("minutes must be positive")
    settings = get_settings()
    total = round(minutes * 60)
    with span("producer", "build_rundown", minutes=minutes, topics=topics or []) as s:
        candidates = await top_stories(
            limit=CANDIDATE_POOL,
            window_hours=settings.producer_freshness_hours,
            min_sources=settings.producer_min_sources,
        )
        if topics:
            candidates = [c for c in candidates if matches_topics(c, topics)]
        wanted = story_count(minutes, settings.producer_seconds_per_story)
        chosen = candidates[: min(wanted, total)]
        if not chosen:
            raise NoStoriesError(
                f"no stories in the last {settings.producer_freshness_hours}h with "
                f"{settings.producer_min_sources}+ sources"
                + (f" matching {topics}" if topics else "")
            )
        seconds = split_evenly(total, len(chosen))

        briefing = Briefing(target_minutes=minutes, status=BriefingStatus.draft)
        async with session_scope() as session:
            session.add(briefing)
        s.briefing_id = briefing.id
        rundown = Rundown(
            briefing_id=briefing.id,
            minutes=minutes,
            items=[
                RundownItem(
                    story_id=story.id,
                    order=i,
                    target_seconds=sec,
                    title=story.title,
                    sources=story.sources,
                )
                for i, (story, sec) in enumerate(zip(chosen, seconds, strict=True))
            ],
        )
        s.set(stories=len(chosen), wanted=wanted, candidates=len(candidates))
    return rundown


async def rundown_for_story(story_id: UUID, seconds: int | None = None) -> Rundown:
    """A one-story rundown (a telecast from the Press feed, task 8.3): its own ``briefings`` row
    and the story's live sources, newest first. ``NoStoriesError`` if the story is unknown or has
    fewer than ``producer_min_sources`` live sources. Old stories are allowed: a reader chose it.
    """
    settings = get_settings()
    seconds = seconds or settings.producer_seconds_per_story
    stories, sources, links = (
        Story.__table__,  # type: ignore[attr-defined]
        Source.__table__,  # type: ignore[attr-defined]
        StorySource.__table__,  # type: ignore[attr-defined]
    )
    seen_at = func.coalesce(sources.c.published_at, sources.c.fetched_at)
    with span("producer", "rundown_for_story", story_id=story_id, seconds=seconds) as s:
        async with get_engine().connect() as conn:
            title = (
                await conn.execute(select(stories.c.title).where(stories.c.id == story_id))
            ).scalar_one_or_none()
            rows = (
                await conn.execute(
                    select(
                        sources.c.id,
                        sources.c.outlet,
                        sources.c.title,
                        sources.c.url,
                        sources.c.published_at,
                    )
                    .join(links, links.c.source_id == sources.c.id)
                    .where(links.c.story_id == story_id, sources.c.retracted.is_(False))
                    .order_by(seen_at.desc(), sources.c.id)
                )
            ).all()
        if title is None or len(rows) < settings.producer_min_sources:
            raise NoStoriesError(
                f"story {story_id} is unknown or has fewer than "
                f"{settings.producer_min_sources} live sources"
            )
        briefing = Briefing(target_minutes=round(seconds / 60, 2), status=BriefingStatus.draft)
        async with session_scope() as session:
            session.add(briefing)
        s.briefing_id = briefing.id
        s.set(sources=len(rows))
        return Rundown(
            briefing_id=briefing.id,
            minutes=briefing.target_minutes,
            items=[
                RundownItem(
                    story_id=story_id,
                    order=0,
                    target_seconds=seconds,
                    title=title,
                    sources=[
                        StorySourceRef(
                            id=r.id,
                            outlet=r.outlet,
                            title=r.title,
                            url=r.url,
                            published_at=r.published_at,
                        )
                        for r in rows
                    ],
                )
            ],
        )
