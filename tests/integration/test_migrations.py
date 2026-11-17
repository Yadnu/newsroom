"""Runs the Alembic migrations against a real Postgres with pgvector.

Needs ``NEWSROOM_TEST_DATABASE_URL`` pointing at a throwaway database (it is wiped), e.g.
``postgresql+asyncpg://newsroom:newsroom@localhost:5432/newsroom_test`` from docker compose.
"""

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel

from alembic import command
from app.db import EMBEDDING_DIM

pytestmark = pytest.mark.integration
URL = os.environ.get("NEWSROOM_TEST_DATABASE_URL")
ROOT = Path(__file__).resolve().parents[2]


def _vec(hot: int) -> str:
    return "[" + ",".join("1" if i == hot else "0" for i in range(EMBEDDING_DIM)) + "]"


@pytest.fixture(scope="module")
def alembic_cfg() -> Iterator[Config]:
    if not URL:
        pytest.skip("NEWSROOM_TEST_DATABASE_URL not set")
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.attributes["database_url"] = URL
    cfg.attributes["configure_logger"] = False
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield cfg
    command.downgrade(cfg, "base")


@pytest.fixture
async def engine(alembic_cfg: Config) -> AsyncIterator[AsyncEngine]:
    assert URL
    eng = create_async_engine(URL)
    yield eng
    await eng.dispose()


async def test_schema_matches_models(engine: AsyncEngine) -> None:
    def diff(conn: Any) -> list[Any]:
        return list(compare_metadata(MigrationContext.configure(conn), SQLModel.metadata))

    async with engine.connect() as conn:
        assert await conn.run_sync(diff) == []


async def test_hnsw_indexes_exist(engine: AsyncEngine) -> None:
    sql = "SELECT indexdef FROM pg_indexes WHERE indexname LIKE '%hnsw'"
    async with engine.connect() as conn:
        defs = [r[0] for r in await conn.execute(text(sql))]
    assert len(defs) == 2
    assert all("USING hnsw" in d and "vector_cosine_ops" in d for d in defs)


INSERT_SOURCES = """
INSERT INTO sources (id, url, outlet, title, fetched_at, content, content_hash,
                     trust_score, retracted, embedding)
VALUES (gen_random_uuid(), 'https://a.test/1', 'A', 't', now(), 'c', 'h1', 0.5, false,
        CAST(:near AS vector)),
       (gen_random_uuid(), 'https://b.test/2', 'B', 't', now(), 'c', 'h2', 0.5, false,
        CAST(:far AS vector))
"""

INSERT_CHAIN = """
WITH b AS (
    INSERT INTO briefings VALUES (gen_random_uuid(), now(), 'draft', 3) RETURNING id
), l AS (
    INSERT INTO script_lines (id, briefing_id, "order", text)
    SELECT gen_random_uuid(), id, 0, 'line' FROM b RETURNING id
), c AS (
    INSERT INTO claims (id, script_line_id, text, verdict, rewrite_round)
    SELECT gen_random_uuid(), id, 'claim', 'approved', 0 FROM l RETURNING id
)
INSERT INTO claim_evidence (id, claim_id, source_id, passage)
SELECT gen_random_uuid(), c.id, s.id, 'p' FROM c, sources s WHERE s.content_hash = 'h1'
"""


async def test_cosine_search_and_delete_rules(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(INSERT_SOURCES), {"near": _vec(0), "far": _vec(1)})
        top = await conn.execute(
            text("SELECT url FROM sources ORDER BY embedding <=> CAST(:q AS vector) LIMIT 1"),
            {"q": _vec(0)},
        )
        assert top.scalar_one() == "https://a.test/1"
        await conn.execute(text(INSERT_CHAIN))

    # A source with evidence pointing at it cannot be deleted.
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM sources WHERE content_hash = 'h1'"))

    # Deleting the briefing cascades down to the evidence.
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM briefings"))
        left = await conn.execute(text("SELECT count(*) FROM claim_evidence"))
        assert left.scalar_one() == 0
        await conn.execute(text("DELETE FROM sources"))
