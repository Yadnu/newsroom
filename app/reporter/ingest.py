"""Scheduled RSS ingest: fetch every configured feed, store new ``sources``.

Dedupe happens twice: within the run (by normalized URL and content_hash, first one wins), then in
Postgres with ``INSERT ... ON CONFLICT DO NOTHING`` against the unique ``url`` and ``content_hash``.
Conditional GET (ETag / Last-Modified) keeps unchanged feeds cheap. Validators are only remembered
after the run's rows are stored, so a failed store never hides entries from the next run.
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

import httpx
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.archive import span
from app.config import FeedConfig, get_settings
from app.db.models import Source, utcnow
from app.db.session import get_engine
from app.log import get_logger
from app.reporter.parse import FeedEntry, FeedParseError, content_hash, parse_feed

MAX_FEED_BYTES = 5_000_000
INSERT_CHUNK = 500  # stays well under Postgres' 32767 bind-parameter limit

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class NewSource:
    url: str
    outlet: str
    title: str
    content: str
    content_hash: str
    trust_score: float
    published_at: datetime | None = None
    image_url: str | None = None


StoreFn = Callable[[Sequence[NewSource]], Awaitable[int]]


class IngestReport(BaseModel):
    feeds_total: int = 0
    feeds_failed: int = 0
    feeds_not_modified: int = 0
    entries_seen: int = 0
    new_sources: int = 0
    duplicates: int = 0
    errors: dict[str, str] = {}


@dataclass(slots=True)
class _FeedResult:
    feed: FeedConfig
    entries: list[FeedEntry] = field(default_factory=list)
    not_modified: bool = False
    error: str | None = None
    validators: tuple[str | None, str | None] | None = None


# feed url -> (etag, last_modified). Per process; the worker is long-lived.
_validators: dict[str, tuple[str | None, str | None]] = {}


async def insert_new_sources(rows: Sequence[NewSource]) -> int:
    """Insert rows, skipping any whose url or content_hash already exists. Returns rows inserted."""
    inserted = 0
    table = Source.__table__  # type: ignore[attr-defined]
    async with get_engine().begin() as conn:
        for i in range(0, len(rows), INSERT_CHUNK):
            values = [
                {
                    "id": uuid4(),
                    "url": r.url,
                    "outlet": r.outlet,
                    "title": r.title,
                    "content": r.content,
                    "content_hash": r.content_hash,
                    "trust_score": r.trust_score,
                    "published_at": r.published_at,
                    "fetched_at": utcnow(),
                    "retracted": False,
                    "image_url": r.image_url,
                }
                for r in rows[i : i + INSERT_CHUNK]
            ]
            stmt = pg_insert(table).values(values).on_conflict_do_nothing().returning(table.c.id)
            inserted += len((await conn.execute(stmt)).all())
        # Sources stored before task 8.2 (or before the feed carried one) get their thumbnail now.
        images = [{"u": r.url, "img": r.image_url} for r in rows if r.image_url]
        if images:
            await conn.execute(
                text("UPDATE sources SET image_url = :img WHERE url = :u AND image_url IS NULL"),
                images,
            )
    return inserted


async def ingest_feeds(
    feeds: Sequence[FeedConfig] | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    store: StoreFn = insert_new_sources,
) -> IngestReport:
    settings = get_settings()
    feeds = list(settings.reporter_feeds if feeds is None else feeds)
    report = IngestReport(feeds_total=len(feeds))
    with span("reporter", "ingest_feeds", feeds=len(feeds)) as s:
        sem = asyncio.Semaphore(settings.reporter_max_concurrency)
        async with httpx.AsyncClient(
            timeout=settings.reporter_fetch_timeout_s,
            transport=transport,
            follow_redirects=True,
            headers={"User-Agent": settings.reporter_user_agent},
        ) as client:
            results = await asyncio.gather(*(_fetch(client, sem, f) for f in feeds))

        rows = _dedupe(results, report)
        report.new_sources = await store(rows) if rows else 0
        report.duplicates = report.entries_seen - report.new_sources
        for r in results:
            if r.validators is not None:
                _validators[r.feed.url] = r.validators
        s.set(**report.model_dump(exclude={"errors"}), failed_feeds=list(report.errors))
    log.info("reporter.ingest", **report.model_dump(exclude={"errors"}))
    return report


async def _fetch(
    client: httpx.AsyncClient, sem: asyncio.Semaphore, feed: FeedConfig
) -> _FeedResult:
    result = _FeedResult(feed=feed)
    async with sem:
        with span("reporter", "fetch_feed", feed=feed.url, outlet=feed.outlet) as s:
            headers: dict[str, str] = {}
            etag, modified = _validators.get(feed.url, (None, None))
            if etag:
                headers["If-None-Match"] = etag
            if modified:
                headers["If-Modified-Since"] = modified
            try:
                resp = await client.get(feed.url, headers=headers)
                if resp.status_code == 304:
                    result.not_modified = True
                elif resp.status_code != 200:
                    result.error = f"HTTP {resp.status_code}"
                elif len(resp.content) > MAX_FEED_BYTES:
                    result.error = "feed too large"
                else:
                    result.entries = parse_feed(resp.content)
                    result.validators = (
                        resp.headers.get("etag"),
                        resp.headers.get("last-modified"),
                    )
            except httpx.HTTPError as e:
                result.error = type(e).__name__
            except FeedParseError as e:
                result.error = f"parse error: {e}"
            s.set(entries=len(result.entries), not_modified=result.not_modified)
            if result.error:
                s.set(failed=result.error)
                log.warning("reporter.feed_failed", feed=feed.url, error=result.error)
    return result


def _dedupe(results: Sequence[_FeedResult], report: IngestReport) -> list[NewSource]:
    seen_urls: set[str] = set()
    seen_hashes: set[str] = set()
    rows: list[NewSource] = []
    for r in results:
        if r.error:
            report.feeds_failed += 1
            report.errors[r.feed.url] = r.error
            continue
        if r.not_modified:
            report.feeds_not_modified += 1
        for e in r.entries:
            report.entries_seen += 1
            h = content_hash(e.title, e.content)
            if e.url in seen_urls or h in seen_hashes:
                continue
            seen_urls.add(e.url)
            seen_hashes.add(h)
            rows.append(
                NewSource(
                    url=e.url,
                    outlet=r.feed.outlet,
                    title=e.title,
                    content=e.content,
                    content_hash=h,
                    trust_score=r.feed.trust_score,
                    published_at=e.published_at,
                    image_url=e.image_url,
                )
            )
    return rows
