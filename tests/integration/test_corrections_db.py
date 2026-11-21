"""The correction pipeline against real tables (task 6.2): retract -> flag -> queue -> clear.

Needs ``NEWSROOM_TEST_DATABASE_URL`` pointing at a throwaway database (it is wiped).
"""

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from alembic import command
from app.archive import list_corrections
from app.archive.briefings import briefing_detail
from app.config import get_settings
from app.db import (
    Briefing,
    BriefingStatus,
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
from app.reporter.retract import SourceNotFoundError, retract_source
from app.standards_desk import BlockRule, NotClearedError
from app.standards_desk.corrections import correction_text, queue_corrections
from app.standards_desk.stored import clear_stored, load_script

pytestmark = pytest.mark.integration
URL = os.environ.get("NEWSROOM_TEST_DATABASE_URL")
ROOT = Path(__file__).resolve().parents[2]
ORPHAN = "Acme began shipping its Nova chip this week."
WEAK = "Acme said Nova uses less power."


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


def _source(outlet: str) -> Source:
    return Source(
        url=f"https://{outlet}.test/{uuid4()}",
        outlet=outlet,
        title=f"{outlet} story",
        content="Acme began shipping its Nova chip this week, the company said.",
        content_hash=uuid4().hex * 2,
    )


@dataclass
class World:
    bad: Source
    aired: UUID
    unaired: UUID
    story: UUID


async def _briefing(status: BriefingStatus, story: Story, bad: Source, good: Source) -> UUID:
    """Two approved lines: one judged only on ``bad`` (orphaned), one on ``bad`` + ``good``."""
    b = Briefing(target_minutes=1, status=status)
    async with session_scope() as s:
        s.add(b)
        await s.flush()
        for order, (line_text, sources) in enumerate([(ORPHAN, [bad]), (WEAK, [bad, good])]):
            ln = ScriptLine(briefing_id=b.id, story_id=story.id, order=order, text=line_text)
            s.add(ln)
            await s.flush()
            c = Claim(script_line_id=ln.id, text=line_text, verdict=Verdict.approved, score=0.9)
            s.add(c)
            await s.flush()
            for src in sources:
                s.add(ClaimSource(claim_id=c.id, source_id=src.id))
                s.add(ClaimEvidence(claim_id=c.id, source_id=src.id, passage="p", score=0.8))
    return b.id


async def _world() -> World:
    story, bad, good = Story(title="Acme chip"), _source("ledger"), _source("wire")
    async with session_scope() as s:
        s.add_all([story, bad, good])
    aired = await _briefing(BriefingStatus.aired, story, bad, good)
    unaired = await _briefing(BriefingStatus.cleared, story, bad, good)
    return World(bad, aired, unaired, story.id)


async def test_retraction_flags_briefings_and_airs_a_correction(db: AsyncEngine) -> None:
    w = await _world()
    report = await retract_source(w.bad.url, "publisher withdrew the story")
    assert not report.already and report.on_air == 1
    by_briefing = {b.briefing_id: b for b in report.briefings}
    assert (by_briefing[w.aired].orphaned, by_briefing[w.aired].weakened) == (1, 1)
    assert by_briefing[w.unaired].on_air == 0  # never aired: nothing to correct on air

    again = await retract_source(w.bad.id, "again")
    assert again.already and again.briefings == ()

    # The unaired briefing re-clears without the orphaned line; the weakened one still airs.
    cleared = await clear_stored(w.unaired)
    assert [ln.text for ln in cleared.lines] == [WEAK]
    assert cleared.blocked[0].rule == BlockRule.unapproved

    # The next briefing opens with the correction, and the Standards Desk clears it.
    nxt = Briefing(target_minutes=1)
    async with session_scope() as s:
        s.add(nxt)
        await s.flush()
        s.add(ScriptLine(briefing_id=nxt.id, story_id=w.story, order=0, text="Now to markets."))
    (queued,) = await queue_corrections(nxt.id)
    assert queued.order == -1 and queued.text == correction_text(ORPHAN, "ledger")
    assert await queue_corrections(nxt.id) == []  # not queued twice

    script = await load_script(nxt.id)
    assert [(ln.kind, ln.order) for ln in script.lines] == [("correction", -1), ("script", 0)]
    out = await clear_stored(nxt.id)
    assert out.lines[0].text == queued.text and out.blocked == ()

    rows = await list_corrections()
    assert len(rows) == 4 and {r.impact for r in rows} == {"orphaned", "weakened"}
    (due,) = [r for r in rows if r.on_air]
    assert due.correction_line_id == queued.id and due.correction_briefing_id == nxt.id
    assert due.reason == "publisher withdrew the story" and due.retracted_at is not None
    detail = await briefing_detail(w.aired)
    assert detail.briefing.corrections == 2 and len(detail.corrections) == 2


async def test_tampered_correction_line_is_blocked(db: AsyncEngine) -> None:
    w = await _world()
    await retract_source(w.bad.id, "withdrawn")
    nxt = Briefing(target_minutes=1)
    async with session_scope() as s:
        s.add(nxt)
    (queued,) = await queue_corrections(nxt.id)
    async with db.begin() as conn:
        await conn.execute(
            text("UPDATE script_lines SET text = :t WHERE id = :id"),
            {"t": queued.text.replace("withdrawn", "confirmed"), "id": queued.id},
        )
    with pytest.raises(NotClearedError) as e:
        await clear_stored(nxt.id)
    assert e.value.blocked[0].rule == BlockRule.correction


async def test_unknown_source(db: AsyncEngine) -> None:
    with pytest.raises(SourceNotFoundError):
        await retract_source("https://nowhere.test/x", "r")
