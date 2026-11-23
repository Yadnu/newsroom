"""press_stories and summaries against real Postgres (task 8.2).

Needs ``NEWSROOM_TEST_DATABASE_URL`` (wiped).
"""

import os
from collections.abc import AsyncIterator
from dataclasses import replace
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
from app.press.feed import PressCursor, press_stories
from app.press.summaries import store_summary, stories_needing_summary
from app.reporter.ingest import NewSource, insert_new_sources

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
    db: AsyncEngine,
    title: str,
    members: list[tuple[str, float]],
    retracted: int = 0,
    images: dict[int, str] | None = None,
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
                    " content, content_hash, trust_score, retracted, image_url)"
                    " VALUES (:id, :url, :o, :t, :p, now(), 'c', :h, 0.5, :r, :img)"
                ),
                {
                    "id": src,
                    "url": f"https://{outlet}.test/{src}",
                    "o": outlet,
                    "t": f"{title} via {outlet}",
                    "p": utcnow() - timedelta(hours=hours_ago),
                    "h": src.hex.ljust(64, "0"),
                    "r": i < retracted,
                    "img": (images or {}).get(i),
                },
            )
            await conn.execute(
                text("INSERT INTO story_sources (story_id, source_id) VALUES (:s, :x)"),
                {"s": sid, "x": src},
            )
    return sid


async def test_feed_is_newest_first_and_pages_with_the_cursor(db: AsyncEngine) -> None:
    await _story(db, "newest", [("A", 0.5), ("B", 2)])
    await _story(db, "middle", [("A", 3), ("B", 3)])
    await _story(db, "oldest", [("A", 40), ("B", 41)])
    await _story(db, "single source", [("A", 0.1)])
    await _story(db, "retracted down to one", [("A", 0.2), ("B", 0.2)], retracted=1)

    first = await press_stories(limit=2)
    assert [s.title for s in first] == ["newest", "middle"]
    last = first[-1]
    rest = await press_stories(limit=2, after=PressCursor(latest_at=last.latest_at, id=last.id))
    assert [s.title for s in rest] == ["oldest"]


async def test_feed_story_carries_image_sources_and_summary(db: AsyncEngine) -> None:
    sid = await _story(
        db, "with image", [("A", 1), ("B", 2)], images={1: "https://img.b.test/x.jpg"}
    )
    assert [t for _, t in await stories_needing_summary(10)] == ["with image"]
    await store_summary(sid, "A short paraphrase.")
    assert await stories_needing_summary(10) == []

    (story,) = await press_stories(limit=5)
    assert story.summary == "A short paraphrase."
    assert (story.image_url, story.image_outlet) == ("https://img.b.test/x.jpg", "B")
    assert story.outlets == ["A", "B"] and story.n_sources == 2
    assert [s.outlet for s in story.sources] == ["A", "B"]  # newest first


async def test_ingest_backfills_a_missing_thumbnail(db: AsyncEngine) -> None:
    row = NewSource(
        url="https://a.test/1",
        outlet="A",
        title="T",
        content="c",
        content_hash="1" * 64,
        trust_score=0.5,
    )
    assert await insert_new_sources([row]) == 1
    again = replace(row, image_url="https://img.a.test/1.jpg")
    assert await insert_new_sources([again]) == 0
    async with db.connect() as conn:
        img = (await conn.execute(text("SELECT image_url FROM sources"))).scalar_one()
    assert img == "https://img.a.test/1.jpg"
