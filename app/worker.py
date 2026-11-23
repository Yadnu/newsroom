"""ARQ worker: scheduled jobs. Run with ``uv run arq app.worker.WorkerSettings``.

- ``ingest_job`` every ``reporter_ingest_every_minutes``: ingest, embed, cluster.
- ``recheck_job`` every ``reporter_recheck_every_hours`` at minute 30: retraction recheck.
- ``cleanup_job`` daily at 03:15: telecast audio retention (task 9.1).

Needs Redis (``NEWSROOM_REDIS_URL``) and Postgres. Starts and flushes the archive writer so job
spans reach ``traces`` (decision 0009).
"""

from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings
from arq.cron import CronJob

from app.archive import start_archive, stop_archive
from app.config import get_settings
from app.log import configure_logging, get_logger
from app.press import fill_summaries
from app.press.media import cleanup_media
from app.reporter import cluster_stories, embed_pending_sources, ingest_feeds
from app.reporter.retract import recheck_sources
from app.shared import llm

log = get_logger(__name__)


async def ingest_job(ctx: dict[Any, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
    """Ingest feeds, embed new sources, cluster them into stories, write Press summaries."""
    result: dict[str, Any] = {"ingest": (await ingest_feeds()).model_dump()}
    try:
        result["embedded"] = await embed_pending_sources()
    except llm.LLMConfigError as e:  # e.g. no Voyage key yet: ingest still counts
        log.warning("worker.embed_skipped", reason=str(e))
        result["embedded"] = 0
    stories = await cluster_stories(get_settings().reporter_cluster_window_hours)
    result["stories_touched"] = len(stories)
    try:
        result["summaries"] = await fill_summaries()
    except llm.LLMConfigError as e:  # no chat key: the feed shows titles only
        log.warning("worker.summaries_skipped", reason=str(e))
        result["summaries"] = 0
    return result


async def recheck_job(ctx: dict[Any, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
    """Re-fetch recently cited sources; retract withdrawn ones and queue corrections (task 7.2)."""
    report = await recheck_sources()
    retracted = [r for r in report.retracted if not r.already]
    if retracted:
        log.warning(
            "worker.sources_retracted",
            n=len(retracted),
            urls=[r.url for r in retracted],
            on_air=sum(r.on_air for r in retracted),
        )
    return {
        "checked": report.checked,
        "unreachable": report.unreachable,
        "retracted": [str(r.source_id) for r in retracted],
    }


async def cleanup_job(ctx: dict[Any, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
    """Delete telecast audio past its retention and orphan files (task 9.1)."""
    report = await cleanup_media()
    return {"expired": report.expired, "orphans": report.orphans, "bytes_freed": report.bytes_freed}


async def startup(_ctx: dict[str, Any]) -> None:
    configure_logging(get_settings())
    await start_archive()


async def shutdown(_ctx: dict[str, Any]) -> None:
    await stop_archive()
    await llm.aclose()


def ingest_minutes(every: int) -> set[int]:
    return set(range(0, 60, every))


def recheck_hours(every: int) -> set[int]:
    """Hours of the day the recheck runs; empty when ``every`` is 0 (off)."""
    return set(range(0, 24, every)) if every else set()


def cron_jobs() -> list[CronJob]:
    settings = get_settings()
    jobs = [
        cron(
            ingest_job,
            minute=ingest_minutes(settings.reporter_ingest_every_minutes),
            run_at_startup=True,
            unique=True,
            timeout=600,
        )
    ]
    if hours := recheck_hours(settings.reporter_recheck_every_hours):
        # Minute 30 keeps it clear of the ingest run at minute 0.
        jobs.append(cron(recheck_job, hour=hours, minute=30, unique=True, timeout=900))
    if settings.press_telecast_retention_days > 0:
        jobs.append(cron(cleanup_job, hour={3}, minute=15, unique=True, timeout=600))
    return jobs


class WorkerSettings:
    functions: ClassVar[list[Any]] = [ingest_job, recheck_job, cleanup_job]
    cron_jobs: ClassVar[list[CronJob]] = cron_jobs()
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    on_startup = startup
    on_shutdown = shutdown
