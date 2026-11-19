"""claim_trace() and rejection_log() against real tables.

Needs ``NEWSROOM_TEST_DATABASE_URL`` pointing at a throwaway database (it is wiped).
"""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from alembic import command
from app.archive import TraceNotFoundError, claim_trace, rejection_log
from app.config import get_settings
from app.db import (
    Briefing,
    Claim,
    ClaimEvidence,
    ClaimSource,
    ScriptLine,
    Source,
    Story,
    Trace,
    Verdict,
    session_scope,
)
from app.db.session import get_engine

pytestmark = pytest.mark.integration
URL = os.environ.get("NEWSROOM_TEST_DATABASE_URL")
ROOT = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


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


def _judge_span(
    briefing: UUID, claim_id: UUID, line_id: UUID | None, verdict: str, at: datetime, claim: str
) -> Trace:
    payload: dict[str, Any] = {
        "claim_id": str(claim_id),
        "claim": claim,
        "verdict": verdict,
        "score": 0.9,
        "reason": "ok" if verdict == "approved" else "supported: not in the evidence",
        "checks": {"supported": verdict == "approved", "faithful": True},
        "passages": 2,
        "evidence": 1,
    }
    if line_id is not None:
        payload["line_id"] = str(line_id)
    return Trace(
        briefing_id=briefing,
        component="editor",
        event="judge_claim",
        started_at=at,
        payload=payload,
    )


@pytest.fixture
async def seeded(db: AsyncEngine) -> dict[str, Any]:
    """A line whose first claim was rejected, then rewritten and approved."""
    b, other_b = Briefing(target_minutes=3), Briefing(target_minutes=1)
    story = Story(title="Acme chip")
    wired = Source(
        url="https://wired.test/chip",
        outlet="Wired",
        title="Acme ships chip",
        content="Acme began shipping its chip.",
        content_hash="a" * 64,
    )
    bbc = Source(
        url="https://bbc.test/chip",
        outlet="BBC News",
        title="Acme chip out",
        content="Acme's chip is out.",
        content_hash="b" * 64,
    )
    line = ScriptLine(
        briefing_id=b.id, story_id=story.id, order=3, text="Acme says it ships a chip."
    )
    claim = Claim(
        script_line_id=line.id,
        text="Acme ships a chip.",
        verdict=Verdict.approved,
        score=0.95,
        reason="ok",
        rewrite_round=1,
        judged_at=T0 + timedelta(minutes=2),
    )
    old_claim, legacy_claim = uuid4(), uuid4()
    async with session_scope() as s:
        s.add_all([b, other_b, story, wired, bbc])
        await s.flush()
        s.add(line)
        await s.flush()
        s.add(claim)
        await s.flush()
        s.add_all(
            [
                ClaimSource(claim_id=claim.id, source_id=wired.id),
                ClaimSource(claim_id=claim.id, source_id=bbc.id),
                ClaimEvidence(
                    claim_id=claim.id, source_id=wired.id, passage="Acme began shipping", score=0.8
                ),
                _judge_span(
                    b.id, old_claim, line.id, "rejected", T0, "Acme shipped a billion chips."
                ),
                _judge_span(
                    b.id, claim.id, line.id, "approved", T0 + timedelta(minutes=2), claim.text
                ),
                # Recorded before task 3.1: no line_id.
                _judge_span(b.id, legacy_claim, None, "rewrite", T0 + timedelta(minutes=1), "Old."),
                _judge_span(other_b.id, uuid4(), None, "rejected", T0, "Elsewhere."),
            ]
        )
    return {
        "briefing": b.id,
        "line": line.id,
        "claim": claim.id,
        "old_claim": old_claim,
        "legacy_claim": legacy_claim,
    }


async def test_claim_trace_reaches_source_urls_and_history(seeded: dict[str, Any]) -> None:
    t = await claim_trace(seeded["line"])
    assert t.briefing_id == seeded["briefing"] and t.order == 3 and t.story_title == "Acme chip"
    (c,) = t.claims
    assert c.id == seeded["claim"] and c.verdict == "approved" and c.rewrite_round == 1
    assert {s.url for s in c.cited} == {"https://wired.test/chip", "https://bbc.test/chip"}
    (ev,) = c.evidence
    assert ev.source.url == "https://wired.test/chip" and ev.passage == "Acme began shipping"

    old, new = t.history
    assert (old.claim_id, old.verdict, old.current) == (seeded["old_claim"], "rejected", False)
    assert old.claim == "Acme shipped a billion chips." and old.checks["supported"] is False
    assert (new.claim_id, new.verdict, new.current) == (seeded["claim"], "approved", True)


async def test_claim_trace_unknown_line(seeded: dict[str, Any]) -> None:
    with pytest.raises(TraceNotFoundError):
        await claim_trace(uuid4())


async def test_rejection_log_for_briefing(seeded: dict[str, Any]) -> None:
    rows = await rejection_log(seeded["briefing"])
    assert [r.claim_id for r in rows] == [
        seeded["legacy_claim"],
        seeded["old_claim"],
    ]  # newest first
    legacy, old = rows
    assert legacy.verdict == "rewrite" and legacy.line_id is None and legacy.line_text is None
    assert old.line_id == seeded["line"] and old.line_text == "Acme says it ships a chip."
    assert old.current is False and old.briefing_id == seeded["briefing"]

    only_rejected = await rejection_log(seeded["briefing"], include_rewrite=False)
    assert [r.claim_id for r in only_rejected] == [seeded["old_claim"]]
    assert len(await rejection_log()) == 3  # every briefing
    assert len(await rejection_log(limit=1)) == 1
