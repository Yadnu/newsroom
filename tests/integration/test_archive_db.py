"""DbSink writes spans to the real ``traces`` table.

Needs ``NEWSROOM_TEST_DATABASE_URL`` pointing at a throwaway database (it is wiped).
"""

import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from alembic import command
from app.archive import DbSink, set_sink, span
from app.config import get_settings
from app.db import Briefing, session_scope
from app.db.session import get_engine

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
    command.upgrade(cfg, "head")  # sync: Alembic runs its own event loop


@pytest.fixture
async def db(migrated: None, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncEngine]:
    assert URL
    monkeypatch.setenv("NEWSROOM_DATABASE_URL", URL)
    get_settings.cache_clear()
    get_engine.cache_clear()
    eng = create_async_engine(URL)
    async with eng.begin() as conn:
        await conn.execute(text("TRUNCATE traces, briefings CASCADE"))
    yield eng
    await eng.dispose()
    await get_engine().dispose()
    get_engine.cache_clear()
    get_settings.cache_clear()


async def test_spans_land_in_traces_table(db: AsyncEngine) -> None:
    briefing = Briefing(target_minutes=3)
    async with session_scope() as s:
        s.add(briefing)

    sink = DbSink()
    set_sink(sink)
    with (
        span("producer", "build_rundown", briefing.id) as outer,
        span("llm-gateway", "complete.draft") as inner,
    ):
        inner.add_usage(120, 30, 0.0001)
        inner.set(model="openai/gpt-oss-20b")
    with span("reporter", "ingest.feed", uuid4()):  # unknown briefing: FK fails, row dropped
        pass
    await sink.stop()

    assert sink.written == 2 and sink.dropped == 1
    async with db.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT id, parent_id, briefing_id, component, event, tokens_in, tokens_out,"
                    " cost_usd, latency_ms, payload FROM traces ORDER BY started_at"
                )
            )
        ).all()
    by_event = {r.event: r for r in rows}
    assert set(by_event) == {"build_rundown", "complete.draft"}
    llm = by_event["complete.draft"]
    assert llm.parent_id == outer.id and llm.briefing_id == briefing.id
    assert (llm.tokens_in, llm.tokens_out) == (120, 30)
    assert llm.cost_usd == pytest.approx(0.0001)
    assert llm.payload == {"model": "openai/gpt-oss-20b"}
    assert by_event["build_rundown"].latency_ms >= llm.latency_ms
