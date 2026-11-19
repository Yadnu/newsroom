"""Simple rundown (task 2.0): the top fresh stories, airtime split evenly.

Order follows the Reporter's ranking (most outlets first). Creates the ``briefings`` row so every
later step (Writer, Editor, Anchor) can trace against one ``briefing_id``.
"""

from collections.abc import Sequence
from uuid import UUID

from pydantic import BaseModel, Field

from app.archive import span
from app.config import get_settings
from app.db.models import Briefing, BriefingStatus
from app.db.session import session_scope
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
