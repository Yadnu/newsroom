"""Where telecast jobs run (task 9.3, decision 0029).

``press_telecast_runner``:
- ``auto`` (default): enqueue to the ARQ worker if Redis is reachable and a worker checked in
  recently; otherwise run in this process (as before task 9.3). Queued jobs survive API restarts.
- ``worker``: only the worker; queued even if no worker is up yet; if Redis is down it fails.
- ``inprocess``: always in this process (tests, one-process deployments).

The Redis pool opens lazily with a 1 s connect timeout and no retries; a failure is remembered for
``RETRY_AFTER_S``, so a missing Redis costs one quick attempt a minute, not one per request.
"""

import time
from uuid import UUID

from arq.connections import ArqRedis, RedisSettings, create_pool

from app.config import get_settings
from app.log import get_logger

JOB = "telecast_job"
RETRY_AFTER_S = 60.0
# The worker writes ARQ's health-check key every WORKER_HEALTH_S (it expires a second later), so
# "Redis is up" and "a worker is listening" are told apart: auto mode needs both.
WORKER_HEALTH_S = 15
HEALTH_KEY = "arq:queue:health-check"

log = get_logger(__name__)
_pool: ArqRedis | None = None
_down_until = 0.0


def redis_settings() -> RedisSettings:
    settings = RedisSettings.from_dsn(get_settings().redis_url)
    settings.conn_timeout = 1
    settings.conn_retries = 0
    return settings


async def get_pool() -> ArqRedis | None:
    """The shared ARQ pool, or None while Redis is unreachable."""
    global _pool, _down_until
    if _pool is not None:
        return _pool
    if time.monotonic() < _down_until:
        return None
    try:
        _pool = await create_pool(redis_settings())
    except Exception as e:  # ConnectionError, TimeoutError, OSError, redis errors
        _down_until = time.monotonic() + RETRY_AFTER_S
        log.info("press.queue_unavailable", error=type(e).__name__)
        return None
    return _pool


async def worker_alive(pool: ArqRedis) -> bool:
    return bool(await pool.exists(HEALTH_KEY))


async def enqueue_telecast(telecast_id: UUID, story_id: UUID, *, need_worker: bool = True) -> bool:
    """Queue the job for the worker. False if Redis is unreachable, the enqueue failed, or (with
    ``need_worker``) no worker has checked in within ``WORKER_HEALTH_S``."""
    global _pool
    pool = await get_pool()
    if pool is None:
        return False
    try:
        if need_worker and not await worker_alive(pool):
            log.info("press.no_worker")
            return False
        # A None result means that job id is already queued: it is handled either way.
        await pool.enqueue_job(
            JOB, str(telecast_id), str(story_id), _job_id=f"telecast:{telecast_id}"
        )
    except Exception as e:
        log.warning("press.enqueue_failed", error=type(e).__name__)
        _pool = None  # reconnect next time
        return False
    return True


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


def reset() -> None:
    """Forget a remembered failure (tests)."""
    global _pool, _down_until
    _pool, _down_until = None, 0.0
