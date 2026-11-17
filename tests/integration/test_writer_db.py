"""build_rundown -> draft_script against real Postgres with a fake Groq endpoint.

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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

import app.shared.llm as llm
from alembic import command
from app.config import Settings, get_settings
from app.db.session import get_engine
from app.producer import build_rundown
from app.writer import draft_script

pytestmark = pytest.mark.integration
URL = os.environ.get("NEWSROOM_TEST_DATABASE_URL")
ROOT = Path(__file__).resolve().parents[2]


def groq(req: httpx.Request) -> httpx.Response:
    user = json.loads(req.content)["messages"][1]["content"]
    story = user.split("Story: ", 1)[1].split("\n", 1)[0]
    content = {
        "lines": [
            {
                "text": f"{story}: two outlets report it.",
                "factual": True,
                "claims": [{"text": f"{story} happened.", "sources": ["S1", "S2"]}],
            },
            {"text": "More after this.", "factual": False, "claims": []},
        ]
    }
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": json.dumps(content)}}],
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
    settings = Settings(_env_file=None, groq_api_key="gsk-test", database_url=URL)  # type: ignore[call-arg]
    llm.set_gateway(llm.Gateway(settings, transport=httpx.MockTransport(groq)))
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
                    " VALUES (:id, :url, :o, :t, now(), now(), 'body', :h, 0.5, false)"
                ),
                {
                    "id": src,
                    "url": f"https://{outlet}.test/{src}",
                    "o": outlet,
                    "t": f"{title} via {outlet}",
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


async def test_draft_script_persists_lines_claims_and_citations(db: AsyncEngine) -> None:
    await _story(db, "Chip launch", ["A", "B", "C"])
    await _story(db, "AI probe", ["A", "B"])
    rundown = await build_rundown(1.5)
    script = await draft_script(rundown)

    assert [ln.order for ln in script.lines] == [0, 1, 2, 3]
    assert script.lines[0].text == "Chip launch: two outlets report it."
    rows = await _all(
        db,
        'SELECT "order", text, story_id FROM script_lines WHERE briefing_id = :b ORDER BY "order"',
        b=rundown.briefing_id,
    )
    assert [r.text for r in rows] == [ln.text for ln in script.lines]
    assert rows[0].story_id == rundown.items[0].story_id

    claims = await _all(db, "SELECT id, verdict, text FROM claims ORDER BY text")
    assert [(c.verdict, c.text) for c in claims] == [
        ("pending", "AI probe happened."),
        ("pending", "Chip launch happened."),
    ]
    cited = await _all(
        db,
        "SELECT cs.source_id FROM claim_sources cs JOIN claims c ON c.id = cs.claim_id"
        " WHERE c.text = 'Chip launch happened.'",
    )
    chip_sources = {ref.id for ref in rundown.items[0].sources}
    assert len(cited) == 2 and {r.source_id for r in cited} <= chip_sources
    assert await _all(db, "SELECT 1 FROM claim_evidence") == []  # Writer never writes evidence

    with pytest.raises(IntegrityError):
        async with db.begin() as conn:
            await conn.execute(text("DELETE FROM sources WHERE id = :i"), {"i": cited[0].source_id})
