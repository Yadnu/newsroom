"""build_rundown -> draft_script -> judge_script against real Postgres with fake Groq and Voyage.

Needs ``NEWSROOM_TEST_DATABASE_URL`` pointing at a throwaway database (it is wiped).
"""

import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

import app.shared.llm as llm
from alembic import command
from app.config import Settings, get_settings
from app.db.models import EMBEDDING_DIM
from app.db.session import get_engine
from app.editor import judge_claim, judge_script
from app.producer import build_rundown
from app.writer import draft_script

pytestmark = pytest.mark.integration
URL = os.environ.get("NEWSROOM_TEST_DATABASE_URL")
ROOT = Path(__file__).resolve().parents[2]


def _judgement(passed: bool) -> str:
    checks = {
        n: {"passed": passed or n != "supported", "note": "n"}
        for n in ("supported", "faithful", "attributed", "fresh", "corroborated")
    }
    return json.dumps(
        {**checks, "sensitive": False, "evidence": ["E1"], "confidence": 0.8, "reason": "ok"}
    )


def backend(req: httpx.Request) -> httpx.Response:
    body = json.loads(req.content)
    if req.url.path.endswith("/embeddings"):
        data = [{"index": i, "embedding": [1.0] * EMBEDDING_DIM} for i in range(len(body["input"]))]
        return httpx.Response(200, json={"data": data, "usage": {"total_tokens": 5}})
    user = body["messages"][1]["content"]
    if "Story: " in user:  # Writer
        story = user.split("Story: ", 1)[1].split("\n", 1)[0]
        content = json.dumps(
            {
                "lines": [
                    {
                        "text": f"{story}: two outlets report it.",
                        "factual": True,
                        "claims": [{"text": f"{story} happened.", "sources": ["S1", "S2"]}],
                    }
                ]
            }
        )
    else:  # Editor: approve the chip story, reject the probe
        content = _judgement("<claim>Chip" in user)
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 300, "completion_tokens": 60},
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
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        groq_api_key="gsk-test",
        voyage_api_key="pa-test",
        database_url=URL,
    )
    llm.set_gateway(llm.Gateway(settings, transport=httpx.MockTransport(backend)))
    eng = create_async_engine(URL)
    async with eng.begin() as conn:
        await conn.execute(text("TRUNCATE sources, stories, briefings, traces CASCADE"))
    yield eng
    await llm.aclose()
    await eng.dispose()
    await get_engine().dispose()
    get_engine.cache_clear()
    get_settings.cache_clear()


async def _story(db: AsyncEngine, title: str, outlets: list[str]) -> None:
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
                    " VALUES (:id, :url, :o, :t, now(), now(), :c, :h, 0.5, false)"
                ),
                {
                    "id": src,
                    "url": f"https://{outlet}.test/{src}",
                    "o": outlet,
                    "t": f"{title} via {outlet}",
                    "c": f"{title} happened, {outlet} reports.",
                    "h": src.hex.ljust(64, "0"),
                },
            )
            await conn.execute(
                text("INSERT INTO story_sources (story_id, source_id) VALUES (:s, :x)"),
                {"s": sid, "x": src},
            )


async def _all(db: AsyncEngine, sql: str, **params: Any) -> list[Any]:
    async with db.connect() as conn:
        return list((await conn.execute(text(sql), params)).all())


async def test_judge_script_stores_verdicts_and_evidence(db: AsyncEngine) -> None:
    await _story(db, "Chip launch", ["A", "B"])
    await _story(db, "AI probe", ["A", "B"])
    rundown = await build_rundown(1.5)
    script = await draft_script(rundown)
    judged = await judge_script(script)
    assert len(judged.verdicts) == 2

    claims = await _all(
        db, "SELECT id, text, verdict, score, reason, judged_at FROM claims ORDER BY text"
    )
    assert [(c.text, c.verdict) for c in claims] == [
        ("AI probe happened.", "rejected"),
        ("Chip launch happened.", "approved"),
    ]
    assert all(c.judged_at is not None and c.score == 0.8 for c in claims)
    evidence = await _all(db, "SELECT claim_id, source_id, passage FROM claim_evidence")
    assert [e.claim_id for e in evidence] == [claims[1].id]  # only the approved claim
    cited = await _all(
        db, "SELECT source_id FROM claim_sources WHERE claim_id = :c", c=claims[1].id
    )
    assert evidence[0].source_id in {r.source_id for r in cited}
    (status,) = await _all(db, "SELECT status FROM briefings WHERE id = :b", b=script.briefing_id)
    assert status.status == "judged"

    # Air gate invariant: no approved claim without evidence.
    orphans = await _all(
        db,
        "SELECT c.id FROM claims c LEFT JOIN claim_evidence e ON e.claim_id = c.id"
        " WHERE c.verdict = 'approved' AND e.id IS NULL",
    )
    assert orphans == []

    # Re-judging replaces evidence instead of piling it up.
    chip = next(c for line in script.lines for c in line.claims if c.text.startswith("Chip"))
    await judge_claim(chip)
    rows = await _all(db, "SELECT 1 FROM claim_evidence WHERE claim_id = :c", c=chip.id)
    assert len(rows) == 1
