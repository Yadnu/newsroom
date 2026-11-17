"""top_stories against real Postgres. Needs ``NEWSROOM_TEST_DATABASE_URL`` (wiped)."""

import os
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from alembic import command
from app.config import get_settings
from app.db.models import utcnow
from app.db.session import get_engine
from app.reporter.rank import top_stories

pytestmark = pytest.mark.integration
URL = os.environ.get("NEWSROOM_TEST_DATABASE_URL")
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def migrated() -> None:
    if not URL:
        pytest.skip("NEWSROOM_TEST_DATABASE_URL not set")
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.attributes["database_url"] = URL
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")


@pytest.fixture
async def db(migrated: None, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncEngine]:
    assert URL
    monkeypatch.setenv("NEWSROOM_DATABASE_URL", URL)
    get_settings.cache_clear()
    get_engine.cache_clear()
    eng = create_async_engine(URL)
    async with eng.begin() as conn:
        await conn.execute(text("TRUNCATE sources, stories CASCADE"))
    yield eng
    await eng.dispose()
    await get_engine().dispose()
    get_engine.cache_clear()
    get_settings.cache_clear()


async def _story(
    db: AsyncEngine, title: str, members: list[tuple[str, float]], retracted: int = 0
) -> UUID:
    """members: (outlet, hours_ago). The first ``retracted`` members are marked retracted."""
    sid = uuid4()
    async with db.begin() as conn:
        await conn.execute(
            text("INSERT INTO stories (id, title, created_at) VALUES (:id, :t, now())"),
            {"id": sid, "t": title},
        )
        for i, (outlet, hours_ago) in enumerate(members):
            src = uuid4()
            await conn.execute(
                text(
                    "INSERT INTO sources (id, url, outlet, title, published_at, fetched_at,"
                    " content, content_hash, trust_score, retracted)"
                    " VALUES (:id, :url, :o, :t, :p, now(), 'c', :h, 0.5, :r)"
                ),
                {
                    "id": src,
                    "url": f"https://{outlet}.test/{src}",
                    "o": outlet,
                    "t": f"{title} via {outlet}",
                    "p": utcnow() - timedelta(hours=hours_ago),
                    "h": src.hex.ljust(64, "0"),
                    "r": i < retracted,
                },
            )
            await conn.execute(
                text("INSERT INTO story_sources (story_id, source_id) VALUES (:s, :x)"),
                {"s": sid, "x": src},
            )
    return sid


async def test_ranks_by_outlets_then_sources_then_recency(db: AsyncEngine) -> None:
    await _story(db, "three outlets", [("A", 5), ("B", 5), ("C", 5)])
    await _story(db, "two outlets four sources", [("A", 1), ("A", 1), ("B", 1), ("B", 1)])
    await _story(db, "two outlets two sources fresh", [("A", 0.5), ("B", 0.5)])
    await _story(db, "two outlets two sources older", [("A", 3), ("B", 3)])
    await _story(db, "single source", [("A", 0.1)])
    await _story(db, "stale", [("A", 30), ("B", 30)])
    await _story(db, "retracted down to one", [("A", 1), ("B", 1)], retracted=1)

    top = await top_stories(limit=10, window_hours=24, min_sources=2)
    assert [s.title for s in top] == [
        "three outlets",
        "two outlets four sources",
        "two outlets two sources fresh",
        "two outlets two sources older",
    ]
    first = top[0]
    assert first.n_sources == 3 and first.outlets == ["A", "B", "C"]
    assert len(first.sources) == 3 and all(s.url.startswith("https://") for s in first.sources)
    assert all(s.n_sources >= 2 for s in top)


async def test_limit_and_min_sources(db: AsyncEngine) -> None:
    await _story(db, "big", [("A", 1), ("B", 1), ("C", 1)])
    await _story(db, "small", [("A", 1)])
    assert [s.title for s in await top_stories(limit=1)] == ["big"]
    assert [s.title for s in await top_stories(min_sources=1)] == ["big", "small"]
    assert await top_stories(window_hours=24, min_sources=4) == []
