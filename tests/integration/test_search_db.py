"""search_live() storing into a real ``sources`` table, Tavily mocked (task 5.4).

Needs ``NEWSROOM_TEST_DATABASE_URL`` pointing at a throwaway database (it is wiped).
"""

import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from alembic import command
from app.config import Settings, get_settings
from app.db.session import get_engine
from app.reporter.search import clear_cache, search_live

pytestmark = pytest.mark.integration
URL = os.environ.get("NEWSROOM_TEST_DATABASE_URL")
ROOT = Path(__file__).resolve().parents[2]
BODY = "Nvidia named Colette Kress interim chief executive this week. " * 30


def tavily(req: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "results": [
                {
                    "url": "https://www.reuters.com/tech/nvidia-kress?utm_source=feed",
                    "title": "Nvidia names Kress interim CEO",
                    "content": "snippet",
                    "raw_content": BODY,
                    "published_date": "2026-11-19T09:00:00Z",
                }
            ]
        },
    )


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
    clear_cache()
    eng = create_async_engine(URL)
    async with eng.begin() as conn:
        await conn.execute(text("TRUNCATE sources, stories, briefings, traces CASCADE"))
    yield eng
    await eng.dispose()
    await get_engine().dispose()
    get_engine.cache_clear()
    get_settings.cache_clear()


async def test_live_results_are_stored_once_and_read_back(db: AsyncEngine) -> None:
    settings: Any = Settings(  # type: ignore[call-arg]
        _env_file=None, database_url=URL, tavily_api_key="tvly-test", reporter_search_cache_s=0
    )
    transport = httpx.MockTransport(tavily)
    (first,) = await search_live("nvidia ceo", settings=settings, transport=transport)
    (again,) = await search_live("nvidia ceo", settings=settings, transport=transport)
    assert first.id == again.id  # same URL: reused, not inserted twice
    assert first.url == "https://www.reuters.com/tech/nvidia-kress"
    async with db.connect() as conn:
        rows = (
            await conn.execute(
                text("SELECT outlet, trust_score, content, published_at FROM sources")
            )
        ).all()
    (row,) = rows
    assert (row.outlet, row.trust_score) == ("Reuters", 0.5)
    assert row.content.startswith("Nvidia named") and row.published_at is not None
