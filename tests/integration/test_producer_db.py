"""build_rundown against real Postgres. Needs ``NEWSROOM_TEST_DATABASE_URL`` (wiped)."""

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
from app.archive import DbSink, set_sink
from app.config import get_settings
from app.db.models import utcnow
from app.db.session import get_engine
from app.producer import NoStoriesError, build_rundown

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
        await conn.execute(text("TRUNCATE sources, stories, briefings, traces CASCADE"))
    yield eng
    await eng.dispose()
    await get_engine().dispose()
    get_engine.cache_clear()
    get_settings.cache_clear()


async def _story(db: AsyncEngine, title: str, outlets: list[str], hours_ago: float = 1) -> UUID:
    sid = uuid4()
    async with db.begin() as conn:
        await conn.execute(
            text("INSERT INTO stories (id, title, created_at) VALUES (:id, :t, now())"),
            {"id": sid, "t": title},
        )
        for outlet in outlets:
            src = uuid4()
            await conn.execute(
                text(
                    "INSERT INTO sources (id, url, outlet, title, published_at, fetched_at,"
                    " content, content_hash, trust_score, retracted)"
                    " VALUES (:id, :url, :o, :t, :p, now(), 'c', :h, 0.5, false)"
                ),
                {
                    "id": src,
                    "url": f"https://{outlet}.test/{src}",
                    "o": outlet,
                    "t": f"{title} via {outlet}",
                    "p": utcnow() - timedelta(hours=hours_ago),
                    "h": src.hex.ljust(64, "0"),
                },
            )
            await conn.execute(
                text("INSERT INTO story_sources (story_id, source_id) VALUES (:s, :x)"),
                {"s": sid, "x": src},
            )
    return sid


async def test_build_rundown_persists_briefing_and_trace(db: AsyncEngine) -> None:
    big = await _story(db, "Chip launch", ["A", "B", "C"])
    mid = await _story(db, "AI probe", ["A", "B"])
    await _story(db, "Single source", ["A"])
    await _story(db, "Stale", ["A", "B"], hours_ago=40)

    sink = DbSink()
    set_sink(sink)
    rundown = await build_rundown(3)
    await sink.stop()

    assert [i.story_id for i in rundown.items] == [big, mid]
    assert [i.target_seconds for i in rundown.items] == [90, 90]
    async with db.connect() as conn:
        b = (
            await conn.execute(
                text("SELECT status, target_minutes FROM briefings WHERE id = :id"),
                {"id": rundown.briefing_id},
            )
        ).one()
        t = (
            await conn.execute(
                text("SELECT briefing_id, payload FROM traces WHERE event = 'build_rundown'")
            )
        ).one()
    assert (b.status, b.target_minutes) == ("draft", 3)
    assert t.briefing_id == rundown.briefing_id and t.payload["stories"] == 2


async def test_no_fresh_stories_creates_no_briefing(db: AsyncEngine) -> None:
    await _story(db, "Stale", ["A", "B"], hours_ago=40)
    with pytest.raises(NoStoriesError):
        await build_rundown(3)
    async with db.connect() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM briefings"))).scalar_one() == 0
