from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

import app.producer.rundown as rundown_mod
from app.archive import MemorySink
from app.db.models import Briefing, BriefingStatus
from app.producer import NoStoriesError, build_rundown
from app.producer.rundown import split_evenly, story_count
from app.reporter.rank import StorySourceRef, TopStory

WHEN = datetime(2026, 11, 17, 8, 0, tzinfo=UTC)


def _story(title: str, source_titles: tuple[str, ...] = ("a", "b")) -> TopStory:
    refs = [
        StorySourceRef(
            id=uuid4(), outlet=f"O{i}", title=t, url=f"https://o{i}.test/{title}", published_at=WHEN
        )
        for i, t in enumerate(source_titles)
    ]
    return TopStory(
        id=uuid4(),
        title=title,
        n_sources=len(refs),
        outlets=[r.outlet for r in refs],
        latest_at=WHEN,
        sources=refs,
    )


class FakeSession:
    def __init__(self, saved: list[Any]) -> None:
        self.saved = saved

    def add(self, obj: Any) -> None:
        self.saved.append(obj)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"stories": [], "saved": []}

    async def fake_top(limit: int, window_hours: int, min_sources: int) -> list[TopStory]:
        state["top_args"] = (limit, window_hours, min_sources)
        return list(state["stories"])

    @asynccontextmanager
    async def fake_scope() -> AsyncIterator[FakeSession]:
        yield FakeSession(state["saved"])

    monkeypatch.setattr(rundown_mod, "top_stories", fake_top)
    monkeypatch.setattr(rundown_mod, "session_scope", fake_scope)
    return state


# ---- pure helpers -----------------------------------------------------------------------------


@pytest.mark.parametrize(("minutes", "want"), [(3, 4), (1, 1), (0.25, 1), (5, 7), (10, 13)])
def test_story_count(minutes: float, want: int) -> None:
    assert story_count(minutes, 45) == want


def test_split_evenly_sums_exactly_and_front_loads_remainder() -> None:
    assert split_evenly(180, 4) == [45, 45, 45, 45]
    assert split_evenly(100, 3) == [34, 33, 33]
    assert sum(split_evenly(181, 7)) == 181
    assert split_evenly(10, 0) == []
    with pytest.raises(ValueError):
        split_evenly(2, 3)


# ---- build_rundown ----------------------------------------------------------------------------


async def test_three_minute_rundown_takes_top_four_in_rank_order(
    env: dict[str, Any], trace_sink: MemorySink
) -> None:
    env["stories"] = [_story(f"s{i}") for i in range(6)]
    r = await build_rundown(3)

    assert env["top_args"] == (100, 24, 2)
    assert [i.title for i in r.items] == ["s0", "s1", "s2", "s3"]
    assert [i.order for i in r.items] == [0, 1, 2, 3]
    assert [i.target_seconds for i in r.items] == [45, 45, 45, 45]
    assert r.total_seconds == 180
    assert r.items[0].sources == env["stories"][0].sources

    (briefing,) = env["saved"]
    assert isinstance(briefing, Briefing)
    assert briefing.id == r.briefing_id
    assert briefing.target_minutes == 3 and briefing.status == BriefingStatus.draft

    (t,) = trace_sink.traces
    assert (t.component, t.event, t.briefing_id) == ("producer", "build_rundown", r.briefing_id)
    assert t.payload["stories"] == 4 and t.payload["wanted"] == 4


async def test_fewer_stories_than_wanted_share_the_full_time(env: dict[str, Any]) -> None:
    env["stories"] = [_story("only"), _story("two")]
    r = await build_rundown(3)
    assert [i.target_seconds for i in r.items] == [90, 90]


async def test_topic_filter_matches_title_or_source_titles(env: dict[str, Any]) -> None:
    env["stories"] = [
        _story("Chip launch"),
        _story("Football final"),
        _story("New lab", ("Startup raises money for ROBOTICS", "b")),
    ]
    r = await build_rundown(3, topics=["chip", " robotics "])
    assert [i.title for i in r.items] == ["Chip launch", "New lab"]


async def test_no_matching_stories_raises_and_creates_no_briefing(
    env: dict[str, Any], trace_sink: MemorySink
) -> None:
    env["stories"] = [_story("Football final")]
    with pytest.raises(NoStoriesError, match="matching"):
        await build_rundown(3, topics=["chip"])
    assert env["saved"] == []
    (t,) = trace_sink.traces
    assert t.briefing_id is None and t.error is not None


async def test_rejects_non_positive_minutes(env: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        await build_rundown(0)
