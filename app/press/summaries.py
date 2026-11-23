"""``fill_summaries()``: crawler summaries for new feed stories, refreshed as they grow (8.2, 9.2).

Each summary comes from ``writer.summarize_story()`` and must also pass the Standards Desk's
copied-words rule against the story's sources (a summary paraphrases; it never reproduces an
article). A summary that copies is retried once with that feedback, then skipped. Run by the worker
after clustering and by ``newsroom summarize``.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, or_, select, update

from app.archive import span
from app.config import get_settings
from app.db.models import Source, Story, StorySource
from app.db.session import get_engine
from app.log import get_logger
from app.shared import llm
from app.standards_desk.clear import copied_run
from app.writer.draft import SourceText, WriterError, load_sources
from app.writer.summary import summarize_story

SOURCES_PER_SUMMARY = 4

log = get_logger(__name__)
_stories = Story.__table__  # type: ignore[attr-defined]
_sources = Source.__table__  # type: ignore[attr-defined]
_links = StorySource.__table__  # type: ignore[attr-defined]


@dataclass(frozen=True, slots=True)
class SummaryTodo:
    story_id: UUID
    title: str
    n_sources: int  # live sources now
    refresh: bool  # True: it has a summary, written from fewer sources


async def stories_needing_summary(
    limit: int, min_sources: int = 2, growth: int | None = None
) -> list[SummaryTodo]:
    """Stories without a summary first, then those that gained ``growth`` (default
    ``press_summary_refresh_growth``) live sources since theirs was written; newest first. Summaries
    from before task 9.2 have no source count and count as written from ``min_sources``."""
    growth = get_settings().press_summary_refresh_growth if growth is None else growth
    seen_at = func.coalesce(_sources.c.published_at, _sources.c.fetched_at)
    n = func.count(_sources.c.id)
    written_from = func.coalesce(_stories.c.summary_sources, min_sources)
    missing = _stories.c.summary.is_(None)
    query = (
        select(_stories.c.id, _stories.c.title, n.label("n"), missing.label("missing"))
        .join(_links, _links.c.story_id == _stories.c.id)
        .join(_sources, _sources.c.id == _links.c.source_id)
        .where(_sources.c.retracted.is_(False))
        .group_by(_stories.c.id, _stories.c.title, _stories.c.summary, _stories.c.summary_sources)
        .having(n >= min_sources)
        .having(or_(missing, n >= written_from + growth))
        .order_by(missing.desc(), func.max(seen_at).desc(), _stories.c.id)
        .limit(limit)
    )
    async with get_engine().connect() as conn:
        rows = (await conn.execute(query)).all()
    return [SummaryTodo(r.id, r.title, int(r.n), not r.missing) for r in rows]


async def story_sources(story_id: UUID, n: int = SOURCES_PER_SUMMARY) -> list[SourceText]:
    seen_at = func.coalesce(_sources.c.published_at, _sources.c.fetched_at)
    query = (
        select(_sources.c.id)
        .join(_links, _links.c.source_id == _sources.c.id)
        .where(_links.c.story_id == story_id, _sources.c.retracted.is_(False))
        .order_by(seen_at.desc(), _sources.c.id)
        .limit(n)
    )
    async with get_engine().connect() as conn:
        ids = [r.id for r in (await conn.execute(query)).all()]
    loaded = await load_sources(ids)
    return [loaded[i] for i in ids if i in loaded]


async def store_summary(story_id: UUID, summary: str | None, n_sources: int) -> None:
    """Store a summary written from ``n_sources`` live sources. ``summary=None`` keeps the old text
    and only records the count (a failed refresh waits until the story grows again)."""
    values: dict[str, object] = {"summary_sources": n_sources}
    if summary is not None:
        values["summary"] = summary
    async with get_engine().begin() as conn:
        await conn.execute(update(_stories).where(_stories.c.id == story_id).values(**values))


async def write_summary(story_id: UUID, title: str, n_sources: int = 0) -> str | None:
    """Summarize one story and store it. None when the writer could not produce a clean one."""
    sources = await story_sources(story_id)
    texts = [f"{s.title}\n{s.content}" for s in sources]
    limit = get_settings().standards_max_copied_words
    feedback: list[str] = []
    for _ in range(2):
        try:
            summary = await summarize_story(story_id, title, sources, feedback)
        except WriterError as e:
            log.warning("press.summary_rejected", story_id=str(story_id), error=str(e)[:300])
            return None
        run = copied_run(summary, texts, limit)
        if run is None:
            await store_summary(story_id, summary, n_sources)
            return summary
        feedback = [f"it copies {limit} words in a row from a source: {run!r}"]
    log.warning("press.summary_copies_source", story_id=str(story_id))
    return None


async def fill_summaries(limit: int | None = None) -> int:
    """Summaries for up to ``limit`` (default ``press_summaries_per_run``) of the newest stories
    without one. Returns how many were written. LLM errors skip a story, never the run."""
    limit = get_settings().press_summaries_per_run if limit is None else limit
    if limit <= 0:
        return 0
    with span("press", "fill_summaries", limit=limit) as s:
        todo = await stories_needing_summary(limit)
        written = 0
        for item in todo:
            try:
                ok = await write_summary(item.story_id, item.title, item.n_sources) is not None
            except llm.LLMConfigError:
                raise
            except llm.LLMError as e:
                log.warning(
                    "press.summary_failed", story_id=str(item.story_id), error=type(e).__name__
                )
                continue  # transient: try again next run
            written += ok
            if not ok and item.refresh:
                await store_summary(item.story_id, None, item.n_sources)  # keep the old summary
        s.set(todo=len(todo), refresh=sum(i.refresh for i in todo), written=written)
    return written
