"""press_stories and summaries against real Postgres (task 8.2).

Needs ``NEWSROOM_TEST_DATABASE_URL`` (wiped).
"""

import os
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from alembic import command
from app.config import get_settings
from app.db.models import utcnow
from app.db.session import get_engine
from app.press import telecast as tc
from app.press.feed import PressCursor, press_stories
from app.press.summaries import store_summary, stories_needing_summary
from app.reporter.ingest import NewSource, insert_new_sources

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
        await conn.execute(text("TRUNCATE sources, stories, briefings CASCADE"))
    yield eng
    await eng.dispose()
    await get_engine().dispose()
    get_engine.cache_clear()
    get_settings.cache_clear()


async def _story(
    db: AsyncEngine,
    title: str,
    members: list[tuple[str, float]],
    retracted: int = 0,
    images: dict[int, str] | None = None,
) -> UUID:
    """members: (outlet, hours_ago). The first ``retracted`` members are marked retracted."""
    sid = uuid4()
    async with db.begin() as conn:
        await conn.execute(
            text("INSERT INTO stories (id, title, created_at) VALUES (:id, :t, now())"),
            {"id": sid, "t": title},
        )
        for i, (outlet, hours_ago) in enumerate(members):
            src = uuid4()
            await conn.execute(
                text(
                    "INSERT INTO sources (id, url, outlet, title, published_at, fetched_at,"
                    " content, content_hash, trust_score, retracted, image_url)"
                    " VALUES (:id, :url, :o, :t, :p, now(), 'c', :h, 0.5, :r, :img)"
                ),
                {
                    "id": src,
                    "url": f"https://{outlet}.test/{src}",
                    "o": outlet,
                    "t": f"{title} via {outlet}",
                    "p": utcnow() - timedelta(hours=hours_ago),
                    "h": src.hex.ljust(64, "0"),
                    "r": i < retracted,
                    "img": (images or {}).get(i),
                },
            )
            await conn.execute(
                text("INSERT INTO story_sources (story_id, source_id) VALUES (:s, :x)"),
                {"s": sid, "x": src},
            )
    return sid


async def test_feed_is_newest_first_and_pages_with_the_cursor(db: AsyncEngine) -> None:
    await _story(db, "newest", [("A", 0.5), ("B", 2)])
    await _story(db, "middle", [("A", 3), ("B", 3)])
    await _story(db, "oldest", [("A", 40), ("B", 41)])
    await _story(db, "single source", [("A", 0.1)])
    await _story(db, "retracted down to one", [("A", 0.2), ("B", 0.2)], retracted=1)

    first = await press_stories(limit=2)
    assert [s.title for s in first] == ["newest", "middle"]
    last = first[-1]
    rest = await press_stories(limit=2, after=PressCursor(latest_at=last.latest_at, id=last.id))
    assert [s.title for s in rest] == ["oldest"]


async def test_feed_story_carries_image_sources_and_summary(db: AsyncEngine) -> None:
    sid = await _story(
        db, "with image", [("A", 1), ("B", 2)], images={1: "https://img.b.test/x.jpg"}
    )
    assert [t for _, t in await stories_needing_summary(10)] == ["with image"]
    await store_summary(sid, "A short paraphrase.")
    assert await stories_needing_summary(10) == []

    (story,) = await press_stories(limit=5)
    assert story.summary == "A short paraphrase."
    assert (story.image_url, story.image_outlet) == ("https://img.b.test/x.jpg", "B")
    assert story.outlets == ["A", "B"] and story.n_sources == 2
    assert [s.outlet for s in story.sources] == ["A", "B"]  # newest first


async def test_ingest_backfills_a_missing_thumbnail(db: AsyncEngine) -> None:
    row = NewSource(
        url="https://a.test/1",
        outlet="A",
        title="T",
        content="c",
        content_hash="1" * 64,
        trust_score=0.5,
    )
    assert await insert_new_sources([row]) == 1
    again = replace(row, image_url="https://img.a.test/1.jpg")
    assert await insert_new_sources([again]) == 0
    async with db.connect() as conn:
        img = (await conn.execute(text("SELECT image_url FROM sources"))).scalar_one()
    assert img == "https://img.a.test/1.jpg"


async def _telecast(
    db: AsyncEngine, story: UUID, step: str, *, minutes_ago: float = 0, **kw: object
) -> UUID:
    tid = uuid4()
    at = utcnow() - timedelta(minutes=minutes_ago)
    async with db.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO telecasts (id, story_id, briefing_id, step, error, audio_path,"
                " duration_ms, created_at, updated_at)"
                " VALUES (:id, :s, :b, :step, :err, :path, :dur, :at, :at)"
            ),
            {
                "id": tid,
                "s": story,
                "b": kw.get("briefing_id"),
                "step": step,
                "err": kw.get("error"),
                "path": kw.get("audio_path"),
                "dur": kw.get("duration_ms"),
                "at": at,
            },
        )
    return tid


async def test_ready_telecast_view_has_audio_lines_and_verdicts(
    db: AsyncEngine, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(tc, "media_dir", lambda: tmp_path)
    sid = await _story(db, "aired story", [("A", 1), ("B", 2)])
    bid, l1, l2, l3 = uuid4(), uuid4(), uuid4(), uuid4()
    async with db.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO briefings (id, created_at, status, target_minutes)"
                " VALUES (:b, now(), 'aired', 0.75)"
            ),
            {"b": bid},
        )
        for lid, order, start, end in ((l1, 0, 0, 4000), (l2, 1, 4300, 9000), (l3, 2, None, None)):
            await conn.execute(
                text(
                    'INSERT INTO script_lines (id, briefing_id, story_id, "order", text, kind,'
                    " audio_start_ms, audio_end_ms, audio_words)"
                    " VALUES (:id, :b, :s, :o, :t, 'script', :st, :en, CAST(:w AS JSONB))"
                ),
                {
                    "id": lid,
                    "b": bid,
                    "s": sid,
                    "o": order,
                    "t": f"line {order}",
                    "st": start,
                    "en": end,
                    "w": '[["line", 0, 2000], ["0", 2000, 4000]]' if order == 0 else None,
                },
            )
        for lid, verdict in ((l1, "approved"), (l2, "approved"), (l3, "rejected")):
            await conn.execute(
                text(
                    "INSERT INTO claims (id, script_line_id, text, verdict, rewrite_round)"
                    " VALUES (:i, :l, 'c', :v, 0)"
                ),
                {"i": uuid4(), "l": lid, "v": verdict},
            )
    (tmp_path / "telecasts").mkdir()
    tid = await _telecast(
        db, sid, "ready", briefing_id=bid, audio_path="telecasts/x.wav", duration_ms=9000
    )
    (tmp_path / "telecasts" / "x.wav").write_bytes(b"RIFF")

    view = await tc.telecast_view(tid)
    assert (
        view.step == "ready"
        and view.audio_url == "/media/telecasts/x.wav"
        and view.duration_ms == 9000
    )
    assert [(ln.text, ln.start_ms, ln.end_ms) for ln in view.lines] == [
        ("line 0", 0, 4000),
        ("line 1", 4300, 9000),
    ]
    assert [w.text for w in view.lines[0].words] == ["line", "0"] and view.lines[1].words == []
    assert view.verdicts == {"approved": 2, "rejected": 1}
    assert (
        view.story is not None and view.story.telecast is not None and view.story.telecast.id == tid
    )

    started: list[UUID] = []
    again = await tc.start_telecast(sid, runner=lambda t, s: started.append(t))
    assert again.id == tid and started == []  # a recent ready telecast is reused


async def test_start_reuses_running_and_replaces_stale_or_failed(
    db: AsyncEngine, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(tc, "media_dir", lambda: tmp_path)
    sid = await _story(db, "story", [("A", 1), ("B", 2)])
    started: list[UUID] = []

    def runner(t: UUID, s: UUID) -> None:
        started.append(t)

    stale = await _telecast(db, sid, "checking", minutes_ago=60)
    assert (await tc.telecast_view(stale)).step == "failed"  # interrupted
    await _telecast(db, sid, "failed", minutes_ago=1, error="clearing: nothing")
    first = await tc.start_telecast(sid, runner=runner)
    assert first.step == "queued" and started == [first.id]
    second = await tc.start_telecast(sid, runner=runner)
    assert second.id == first.id and len(started) == 1  # still running: reused

    with pytest.raises(tc.StoryNotFoundError):
        await tc.start_telecast(uuid4(), runner=runner)
    with pytest.raises(tc.TelecastNotFoundError):
        await tc.telecast_view(uuid4())
