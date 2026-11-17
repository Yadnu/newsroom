"""ARQ worker: scheduled jobs. Run with ``uv run arq app.worker.WorkerSettings``.

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
from app.reporter import cluster_stories, embed_pending_sources, ingest_feeds
from app.shared import llm

log = get_logger(__name__)


async def ingest_job(ctx: dict[Any, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
    """Ingest feeds, embed new sources, cluster them into stories."""
    result: dict[str, Any] = {"ingest": (await ingest_feeds()).model_dump()}
    try:
        result["embedded"] = await embed_pending_sources()
    except llm.LLMConfigError as e:  # e.g. no Voyage key yet: ingest still counts
        log.warning("worker.embed_skipped", reason=str(e))
        result["embedded"] = 0
    stories = await cluster_stories(get_settings().reporter_cluster_window_hours)
    result["stories_touched"] = len(stories)
    return result


async def startup(_ctx: dict[str, Any]) -> None:
    configure_logging(get_settings())
    await start_archive()


async def shutdown(_ctx: dict[str, Any]) -> None:
    await stop_archive()
    await llm.aclose()


def ingest_minutes(every: int) -> set[int]:
    return set(range(0, 60, every))


class WorkerSettings:
    functions: ClassVar[list[Any]] = [ingest_job]
    cron_jobs: ClassVar[list[CronJob]] = [
        cron(
            ingest_job,
            minute=ingest_minutes(get_settings().reporter_ingest_every_minutes),
            run_at_startup=True,
            unique=True,
            timeout=600,
        )
    ]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    on_startup = startup
    on_shutdown = shutdown
