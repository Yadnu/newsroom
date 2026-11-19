"""clear_for_air() against real tables: approved, pending, and retracted-evidence lines.

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
from app.config import get_settings
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
from app.editor import ReviewedScript
from app.standards_desk import BlockRule, NotClearedError, clear_for_air
from app.writer import DraftClaim, DraftLine, Script

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


def _source(outlet: str, retracted: bool = False) -> Source:
    return Source(
        url=f"https://{outlet}.test/{uuid4()}",
        outlet=outlet,
        title=f"{outlet} story",
        content="Acme began shipping its chip to customers this week, the company said.",
        content_hash=uuid4().hex * 2,
        retracted=retracted,
    )


async def _seed(verdicts: list[tuple[str, Verdict, bool]]) -> Script:
    """One line per (text, verdict, evidence_retracted); every claim has one evidence row."""
    b, story = Briefing(target_minutes=1), Story(title="Acme chip")
    live, dead = _source("wired"), _source("gone", retracted=True)
    lines: list[DraftLine] = []
    async with session_scope() as s:
        s.add_all([b, story, live, dead])
        await s.flush()
        for order, (line_text, verdict, retracted) in enumerate(verdicts):
            ln = ScriptLine(briefing_id=b.id, story_id=story.id, order=order, text=line_text)
            s.add(ln)
            await s.flush()
            claim = Claim(script_line_id=ln.id, text=line_text, verdict=verdict, score=0.9)
            s.add(claim)
            await s.flush()
            src = dead if retracted else live
            s.add(ClaimSource(claim_id=claim.id, source_id=src.id))
            if verdict == Verdict.approved:
                s.add(ClaimEvidence(claim_id=claim.id, source_id=src.id, passage="p", score=0.8))
            lines.append(
                DraftLine(
                    id=ln.id,
                    story_id=story.id,
                    order=order,
                    text=line_text,
                    claims=[DraftClaim(id=claim.id, text=line_text, source_ids=[src.id])],
                )
            )
    return Script(briefing_id=b.id, lines=lines)


async def _status(db: AsyncEngine, script: Script) -> str:
    async with db.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT status FROM briefings WHERE id = :b"), {"b": script.briefing_id}
            )
        ).one()
    return str(row.status)


async def test_only_approved_lines_with_live_evidence_clear(db: AsyncEngine) -> None:
    script = await _seed(
        [
            ("Acme says it is shipping its chip.", Verdict.approved, False),
            ("Acme says sales doubled.", Verdict.pending, False),
            ("Acme says it hired staff.", Verdict.approved, True),
        ]
    )
    out = await clear_for_air(ReviewedScript(script=script, verdicts=[], rounds=0))
    assert [ln.id for ln in out.lines] == [script.lines[0].id]
    assert [(b.order, b.rule) for b in out.blocked] == [
        (1, BlockRule.unapproved),
        (2, BlockRule.unapproved),
    ]
    assert "pending" in out.blocked[0].reason and "retracted" in out.blocked[1].reason
    assert await _status(db, script) == "cleared"


async def test_nothing_cleared_marks_briefing_failed(db: AsyncEngine) -> None:
    script = await _seed([("Acme says sales doubled.", Verdict.rejected, False)])
    with pytest.raises(NotClearedError):
        await clear_for_air(ReviewedScript(script=script, verdicts=[], rounds=0))
    assert await _status(db, script) == "failed"
