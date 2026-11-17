"""insert_new_sources against real Postgres: unique url and content_hash dedupe.

Needs ``NEWSROOM_TEST_DATABASE_URL`` pointing at a throwaway database (it is wiped).
"""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from alembic import command
from app.config import get_settings
from app.db.session import get_engine
from app.reporter import insert_new_sources
from app.reporter.ingest import NewSource

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
        await conn.execute(text("TRUNCATE sources CASCADE"))
    yield eng
    await eng.dispose()
    await get_engine().dispose()
    get_engine.cache_clear()
    get_settings.cache_clear()


def _src(url: str, h: str) -> NewSource:
    return NewSource(
        url=url,
        outlet="Outlet",
        title="t",
        content="c",
        content_hash=h.ljust(64, "0"),
        trust_score=0.5,
        published_at=datetime(2026, 11, 16, tzinfo=UTC),
    )


async def test_insert_skips_existing_url_and_hash(db: AsyncEngine) -> None:
    assert (
        await insert_new_sources([_src("https://x.test/1", "a"), _src("https://x.test/2", "b")])
        == 2
    )
    again = [
        _src("https://x.test/1", "c"),  # same url, new hash
        _src("https://x.test/3", "a"),  # new url, same hash
        _src("https://x.test/4", "d"),  # new
    ]
    assert await insert_new_sources(again) == 1
    async with db.connect() as conn:
        urls = (await conn.execute(text("SELECT url FROM sources ORDER BY url"))).scalars().all()
    assert urls == ["https://x.test/1", "https://x.test/2", "https://x.test/4"]
