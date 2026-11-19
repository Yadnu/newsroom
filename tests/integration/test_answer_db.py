"""answer_question() against real tables with fake Groq and Voyage (task 5.3).

Needs ``NEWSROOM_TEST_DATABASE_URL`` pointing at a throwaway database (it is wiped).
"""

import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

import app.shared.llm as llm
from alembic import command
from app.caller import CallerQuestion
from app.config import Settings, get_settings
from app.db import Briefing, ScriptLine, Source, Story, StorySource, session_scope
from app.db.models import EMBEDDING_DIM, BriefingStatus
from app.db.session import get_engine
from app.producer.answer import SAFE_LINE, answer_question
from app.standards_desk import ScreenResult, clear_stored, load_script

pytestmark = pytest.mark.integration
URL = os.environ.get("NEWSROOM_TEST_DATABASE_URL")
ROOT = Path(__file__).resolve().parents[2]
JUDGE_PASS = {"supported", "faithful", "attributed", "fresh", "corroborated"}


def backend(state: dict[str, Any]) -> Any:
    def handle(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        if req.url.path.endswith("/embeddings"):
            data = [
                {"index": i, "embedding": [1.0] * EMBEDDING_DIM} for i in range(len(body["input"]))
            ]
            return httpx.Response(200, json={"data": data, "usage": {"total_tokens": 5}})
        user = body["messages"][1]["content"]
        if "<claim>" in user:  # Editor judge
            ok = state["approve"]
            content = json.dumps(
                {
                    **{n: {"passed": ok, "note": "n"} for n in JUDGE_PASS},
                    "sensitive": False,
                    "evidence": ["E1"],
                    "confidence": 0.9,
                    "reason": "ok" if ok else "not in the evidence",
                }
            )
        else:  # Writer answer
            content = json.dumps(
                {
                    "lines": [
                        {
                            "text": "Wired says Acme began shipping its chip.",
                            "factual": True,
                            "claims": [
                                {"text": "Acme began shipping its chip.", "sources": ["S1"]}
                            ],
                        }
                    ]
                }
            )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 300, "completion_tokens": 60},
            },
        )

    return handle


@pytest.fixture(scope="module")
def migrated() -> None:
    if not URL:
        pytest.skip("NEWSROOM_TEST_DATABASE_URL not set")
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.attributes["database_url"] = URL
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")


@pytest.fixture
async def db(
    migrated: None, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[AsyncEngine, dict[str, Any]]]:
    assert URL
    monkeypatch.setenv("NEWSROOM_DATABASE_URL", URL)
    get_settings.cache_clear()
    get_engine.cache_clear()
    state: dict[str, Any] = {"approve": True}
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        groq_api_key="gsk-test",
        voyage_api_key="pa-test",
        database_url=URL,
    )
    llm.set_gateway(llm.Gateway(settings, transport=httpx.MockTransport(backend(state))))
    eng = create_async_engine(URL)
    async with eng.begin() as conn:
        await conn.execute(text("TRUNCATE sources, stories, briefings, traces CASCADE"))
    yield eng, state
    await llm.aclose()
    await eng.dispose()
    await get_engine().dispose()
    get_engine.cache_clear()
    get_settings.cache_clear()


async def _seed() -> tuple[UUID, UUID]:
    b, story = Briefing(target_minutes=1, status=BriefingStatus.aired), Story(title="Acme chip")
    src = Source(
        url="https://wired.test/chip",
        outlet="Wired",
        title="Acme ships chip",
        content="Acme began shipping its chip to customers this week.",
        content_hash="d" * 64,
    )
    async with session_scope() as s:
        s.add_all([b, story, src])
        await s.flush()
        s.add_all(
            [
                StorySource(story_id=story.id, source_id=src.id),
                ScriptLine(briefing_id=b.id, story_id=story.id, order=0, text="Now to chips."),
            ]
        )
    return b.id, story.id


def _question(story_id: UUID) -> CallerQuestion:
    return CallerQuestion(
        transcript="is acme shipping the chip",
        intent="follow_up",
        story_id=story_id,
        restated="Is Acme shipping the chip?",
        screen=ScreenResult(True, "ok", "", "llm"),
    )


async def _rows(eng: AsyncEngine, sql: str, **params: Any) -> list[Any]:
    async with eng.connect() as conn:
        return list((await conn.execute(text(sql), params)).all())


async def test_answer_is_stored_judged_cleared_and_kept_out_of_replays(
    db: tuple[AsyncEngine, dict[str, Any]],
) -> None:
    eng, _ = db
    briefing, story = await _seed()
    script = await clear_stored(briefing)
    result = await answer_question(_question(story), script)

    assert not result.fallback
    assert [ln.text for ln in result.cleared.lines] == ["Wired says Acme began shipping its chip."]
    (line,) = await _rows(
        eng, "SELECT id, kind, question, \"order\" FROM script_lines WHERE kind = 'answer'"
    )
    assert (line.kind, line.question, line.order) == ("answer", "is acme shipping the chip", 1000)
    (claim,) = await _rows(
        eng, "SELECT id, verdict FROM claims WHERE script_line_id = :l", l=line.id
    )
    assert claim.verdict == "approved"
    assert await _rows(eng, "SELECT 1 FROM claim_evidence WHERE claim_id = :c", c=claim.id)

    (status,) = await _rows(eng, "SELECT status FROM briefings WHERE id = :b", b=briefing)
    assert status.status == "cleared"  # set by clear_stored, not by the answer
    replay = await load_script(briefing)
    assert [ln.text for ln in replay.lines] == ["Now to chips."]


async def test_rejected_answer_falls_back_to_the_safe_line(
    db: tuple[AsyncEngine, dict[str, Any]],
) -> None:
    eng, state = db
    state["approve"] = False
    briefing, story = await _seed()
    script = await clear_stored(briefing)
    result = await answer_question(_question(story), script)
    assert result.fallback and [ln.text for ln in result.cleared.lines] == [SAFE_LINE]
    texts = [
        r.text for r in await _rows(eng, "SELECT text FROM script_lines WHERE kind = 'answer'")
    ]
    assert SAFE_LINE in texts and len(texts) == 2  # the rejected answer and the safe line
