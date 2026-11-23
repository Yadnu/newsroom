"""Telecast job and routes (task 8.3) with the pipeline faked; the DB side is in
tests/integration/test_press_db.py."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

import app.press.telecast as tc
from app.anchor import AnchorConfigError
from app.main import app
from app.producer import NoStoriesError
from app.shared.llm import LLMProviderError
from app.standards_desk import NotClearedError
from app.writer import WriterError

TID, SID, BID = uuid4(), uuid4(), uuid4()


@pytest.fixture
def job(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """Fakes every pipeline step; ``state["fail"] = (step_fn_name, exc)`` makes one raise."""
    state: dict[str, Any] = {"sets": [], "calls": [], "fail": None}

    async def record(_tid: UUID, **values: object) -> None:
        state["sets"].append(values)

    def step(name: str, result: Any) -> Any:
        async def fn(*args: Any, **kwargs: Any) -> Any:
            state["calls"].append(name)
            if state["fail"] and state["fail"][0] == name:
                raise state["fail"][1]
            return result

        return fn

    class Rundown:
        briefing_id = BID

    class Report:
        audio_ms, lines = 21_500, [object(), object()]

    monkeypatch.setattr(tc, "_set", record)
    monkeypatch.setattr(tc, "rundown_for_story", step("rundown", Rundown()))
    monkeypatch.setattr(tc, "draft_script", step("draft", "script"))
    monkeypatch.setattr(tc, "review_script", step("review", "reviewed"))
    monkeypatch.setattr(tc, "clear_for_air", step("clear", "cleared"))
    monkeypatch.setattr(tc, "speak", step("speak", Report()))
    monkeypatch.setattr(tc, "WavFileSession", lambda path, rate: ("wav", path, rate))
    monkeypatch.setattr(tc, "media_dir", lambda: tmp_path)
    return state


async def test_a_telecast_walks_every_step_and_ends_ready(
    job: dict[str, Any], tmp_path: Path
) -> None:
    await tc.run_telecast(TID, SID)
    assert job["calls"] == ["rundown", "draft", "review", "clear", "speak"]
    steps = [s["step"] for s in job["sets"] if "step" in s]
    assert steps == ["writing", "checking", "clearing", "voicing", "ready"]
    assert {"briefing_id": BID} in job["sets"]
    assert job["sets"][-1] == {
        "step": "ready",
        "audio_path": f"telecasts/{TID}.wav",
        "duration_ms": 21_500,
    }
    assert (tmp_path / "telecasts").is_dir()


@pytest.mark.parametrize(
    ("fail_at", "error", "expected"),
    [
        ("rundown", NoStoriesError("x"), "writing: the story no longer has enough live sources"),
        ("draft", WriterError("x"), "writing: the writer could not draft this story"),
        ("review", LLMProviderError("HTTP 429"), "checking: the language model was unavailable"),
        (
            "clear",
            NotClearedError("x", blocked=()),
            "clearing: nothing in this story could be verified well enough to air",
        ),
        ("speak", AnchorConfigError("no key"), "voicing: text-to-speech is not configured"),
        ("speak", ZeroDivisionError(), "voicing: internal error"),
    ],
)
async def test_failures_end_the_job_with_a_reason(
    job: dict[str, Any], fail_at: str, error: Exception, expected: str
) -> None:
    job["fail"] = (fail_at, error)
    await tc.run_telecast(TID, SID)  # never raises
    assert job["sets"][-1] == {"step": "failed", "error": expected}
    assert "speak" not in job["calls"] or fail_at == "speak"


def test_is_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
    assert not tc.is_stale(now - timedelta(minutes=5), now)
    assert tc.is_stale(now - timedelta(minutes=25), now)


# ---- routes ----------------------------------------------------------------------------------


def _view(step: str = "queued") -> tc.TelecastView:
    now = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
    return tc.TelecastView(
        id=TID,
        story_id=SID,
        briefing_id=None,
        step=step,
        error=None,
        created_at=now,
        updated_at=now,
    )


async def _call(method: str, path: str, **kw: Any) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kw)


async def test_telecast_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    async def start(story_id: UUID) -> tc.TelecastView:
        if story_id != SID:
            raise tc.StoryNotFoundError(str(story_id))
        return _view()

    async def view(telecast_id: UUID) -> tc.TelecastView:
        if telecast_id != TID:
            raise tc.TelecastNotFoundError(str(telecast_id))
        return _view("checking")

    monkeypatch.setattr(tc, "start_telecast", start)
    monkeypatch.setattr(tc, "telecast_view", view)
    r = await _call("POST", f"/press/stories/{SID}/telecast")
    assert r.status_code == 202 and r.json()["step"] == "queued"
    assert (await _call("POST", f"/press/stories/{uuid4()}/telecast")).status_code == 404
    r = await _call("GET", f"/press/telecasts/{TID}")
    assert r.status_code == 200 and r.json()["step"] == "checking" and r.json()["lines"] == []
    assert (await _call("GET", f"/press/telecasts/{uuid4()}")).status_code == 404


async def test_media_serves_ranges(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "telecasts").mkdir()
    (tmp_path / "telecasts" / "a.wav").write_bytes(bytes(range(100)))
    (mount,) = [r for r in app.routes if getattr(r, "name", None) == "media"]
    static: Any = mount.app  # type: ignore[attr-defined]
    monkeypatch.setattr(static, "directory", tmp_path)
    monkeypatch.setattr(static, "all_directories", [tmp_path])
    full = await _call("GET", "/media/telecasts/a.wav")
    assert full.status_code == 200 and full.headers["accept-ranges"] == "bytes"
    part = await _call("GET", "/media/telecasts/a.wav", headers={"Range": "bytes=10-19"})
    assert part.status_code == 206 and part.content == bytes(range(10, 20))
    assert (await _call("GET", "/media/telecasts/../../etc/passwd")).status_code == 404


def test_words_of_reads_stored_word_timings_tolerantly() -> None:
    words = tc.words_of([["Hello", 0, 400], ["world", "400", 900], ["bad"], [1, 2, 3], "x"])
    assert [(w.text, w.start_ms, w.end_ms) for w in words] == [
        ("Hello", 0, 400),
        ("world", 400, 900),
    ]
    assert tc.words_of(None) == []
