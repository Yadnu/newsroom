"""embed_pending_sources + cluster_stories against real Postgres, with a fake Voyage endpoint.

Needs ``NEWSROOM_TEST_DATABASE_URL`` pointing at a throwaway database (it is wiped).
"""

import hashlib
import json
import os
import random
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import httpx
import numpy as np
import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

import app.shared.llm as llm
from alembic import command
from app.config import Settings, get_settings
from app.db.models import EMBEDDING_DIM, utcnow
from app.db.session import get_engine
from app.reporter import cluster_stories, embed_pending_sources, insert_new_sources
from app.reporter.ingest import NewSource

pytestmark = pytest.mark.integration
URL = os.environ.get("NEWSROOM_TEST_DATABASE_URL")
ROOT = Path(__file__).resolve().parents[2]
TOPICS = ("chip", "regulator", "robot")


def fake_vector(text_: str) -> list[float]:
    """Topic keyword picks the axis; a per-text jitter keeps vectors distinct but close."""
    v = np.zeros(EMBEDDING_DIM)
    lowered = text_.lower()
    v[next((i for i, t in enumerate(TOPICS) if t in lowered), len(TOPICS))] = 1.0
    rng = random.Random(hashlib.sha256(text_.encode()).hexdigest())
    v += np.array([rng.gauss(0, 0.004) for _ in range(EMBEDDING_DIM)])
    return list(v / np.linalg.norm(v))


def voyage(req: httpx.Request) -> httpx.Response:
    texts = json.loads(req.content)["input"]
    data = [{"index": i, "embedding": fake_vector(t)} for i, t in enumerate(texts)]
    return httpx.Response(200, json={"data": data, "usage": {"total_tokens": 10 * len(texts)}})


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
    settings = Settings(_env_file=None, voyage_api_key="pa-test", database_url=URL)  # type: ignore[call-arg]
    llm.set_gateway(llm.Gateway(settings, transport=httpx.MockTransport(voyage)))
    eng = create_async_engine(URL)
    async with eng.begin() as conn:
        await conn.execute(text("TRUNCATE sources, stories CASCADE"))
    yield eng
    await llm.aclose()
    await eng.dispose()
    await get_engine().dispose()
    get_engine.cache_clear()
    get_settings.cache_clear()


def _src(n: int, title: str, outlet: str = "A", hours_ago: float = 1.0) -> NewSource:
    return NewSource(
        url=f"https://x.test/{n}",
        outlet=outlet,
        title=title,
        content=f"body {n}",
        content_hash=f"{n:064d}",
        trust_score=0.5,
        published_at=utcnow() - timedelta(hours=hours_ago),
    )


async def _story_members(db: AsyncEngine) -> dict[str, list[str]]:
    async with db.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT st.title, s.title AS src FROM stories st"
                    " JOIN story_sources ss ON ss.story_id = st.id"
                    " JOIN sources s ON s.id = ss.source_id ORDER BY s.published_at"
                )
            )
        ).all()
    out: dict[str, list[str]] = {}
    for r in rows:
        out.setdefault(r.title, []).append(r.src)
    return out


async def test_embed_then_cluster_groups_by_topic(db: AsyncEngine) -> None:
    await insert_new_sources(
        [
            _src(1, "Chip maker ships accelerator", "A", 5),
            _src(2, "New chip ships to clouds", "B", 4),
            _src(3, "Regulator opens AI probe", "A", 3),
            _src(4, "Chip shortage eases", "C", 2),
            _src(5, "Old robot news", "A", hours_ago=48),  # outside the window
        ]
    )
    async with db.begin() as conn:
        await conn.execute(
            text("UPDATE sources SET retracted = true WHERE url = 'https://x.test/3'")
        )

    assert await embed_pending_sources() == 4  # retracted source is skipped
    assert await embed_pending_sources() == 0

    stories = await cluster_stories(window_hours=24)
    assert len(stories) == 1
    assert await _story_members(db) == {
        "Chip maker ships accelerator": [
            "Chip maker ships accelerator",
            "New chip ships to clouds",
            "Chip shortage eases",
        ]
    }
    centroid = np.asarray(stories[0].centroid)
    assert centroid.shape == (EMBEDDING_DIM,)
    assert float(np.linalg.norm(centroid)) == pytest.approx(1.0)


async def test_rerun_is_idempotent_and_new_sources_join_existing(db: AsyncEngine) -> None:
    await insert_new_sources(
        [_src(1, "Chip maker ships accelerator"), _src(2, "Regulator fines lab")]
    )
    await embed_pending_sources()
    first = await cluster_stories()
    assert len(first) == 2
    assert await cluster_stories() == []  # nothing pending

    await insert_new_sources([_src(3, "Second chip report", "B", 0.5)])
    await embed_pending_sources()
    (updated,) = await cluster_stories()
    assert updated.title == "Chip maker ships accelerator"
    members = await _story_members(db)
    assert members["Chip maker ships accelerator"] == [
        "Chip maker ships accelerator",
        "Second chip report",
    ]
    async with db.connect() as conn:
        n_stories = (await conn.execute(text("SELECT count(*) FROM stories"))).scalar_one()
    assert n_stories == 2
