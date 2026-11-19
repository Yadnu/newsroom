"""clear_stored() + speak() with the fake TTS against real tables (task 4.2).

Needs ``NEWSROOM_TEST_DATABASE_URL`` pointing at a throwaway database (it is wiped).
"""

import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from alembic import command
from app.anchor import FakeTTSService, MemorySession, speak
from app.config import Settings, get_settings
from app.db import (
    Briefing,
    Claim,
    ClaimEvidence,
    ClaimSource,
    ScriptLine,
    Source,
    Story,
    Verdict,
    session_scope,
)
from app.db.session import get_engine
from app.standards_desk import BriefingNotFoundError, clear_stored, load_script

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


async def _seed() -> dict[str, UUID]:
    b, story = Briefing(target_minutes=1), Story(title="Acme chip")
    src = Source(
        url="https://wired.test/chip",
        outlet="Wired",
        title="Acme chip",
        content="Acme began shipping its chip to customers this week.",
        content_hash="c" * 64,
    )
    good = ScriptLine(briefing_id=b.id, story_id=story.id, order=0, text="Acme says it ships.")
    bad = ScriptLine(briefing_id=b.id, story_id=story.id, order=1, text="Acme says sales doubled.")
    async with session_scope() as s:
        s.add_all([b, story, src])
        await s.flush()
        s.add_all([good, bad])
        await s.flush()
        ok = Claim(script_line_id=good.id, text="Acme ships.", verdict=Verdict.approved, score=0.9)
        pending = Claim(script_line_id=bad.id, text="Sales doubled.", verdict=Verdict.pending)
        s.add_all([ok, pending])
        await s.flush()
        s.add_all(
            [
                ClaimSource(claim_id=ok.id, source_id=src.id),
                ClaimSource(claim_id=pending.id, source_id=src.id),
                ClaimEvidence(claim_id=ok.id, source_id=src.id, passage="Acme began", score=0.8),
            ]
        )
    return {"briefing": b.id, "good": good.id, "bad": bad.id, "src": src.id}


async def test_speak_stored_briefing_writes_timestamps_and_airs(db: AsyncEngine) -> None:
    ids = await _seed()
    script = await load_script(ids["briefing"])
    assert [ln.id for ln in script.lines] == [ids["good"], ids["bad"]]
    assert script.lines[0].claims[0].source_ids == [ids["src"]]

    cleared = await clear_stored(ids["briefing"])
    assert [ln.id for ln in cleared.lines] == [ids["good"]]
    settings: Any = Settings(_env_file=None, anchor_tts="fake")  # type: ignore[call-arg]
    report = await speak(
        cleared, MemorySession(), tts=FakeTTSService(sample_rate=24000), settings=settings
    )
    assert report.completed

    async with db.connect() as conn:
        rows = {
            r.id: (r.audio_start_ms, r.audio_end_ms)
            for r in await conn.execute(
                text("SELECT id, audio_start_ms, audio_end_ms FROM script_lines")
            )
        }
        status = (
            await conn.execute(
                text("SELECT status FROM briefings WHERE id = :b"), {"b": ids["briefing"]}
            )
        ).scalar_one()
    assert rows[ids["good"]] == (0, report.lines[0].end_ms) and report.lines[0].end_ms > 0
    assert rows[ids["bad"]] == (None, None)  # blocked: never spoken
    assert status == "aired"


async def test_unknown_briefing(db: AsyncEngine) -> None:
    with pytest.raises(BriefingNotFoundError):
        await clear_stored(uuid4())
