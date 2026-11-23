"""speak(): Pipecat pipeline with the fake TTS (task 4.2). No network, DB writes faked."""

import asyncio
import time
from typing import Any
from uuid import UUID, uuid4

import pytest
from pipecat.services.cartesia.tts import CartesiaTTSService

import app.anchor.pipeline as speak_mod
from app.anchor import (
    AnchorConfigError,
    FakeTTSService,
    LineTiming,
    MemorySession,
    make_tts,
    speak,
)
from app.anchor.tts import fake_audio_bytes
from app.archive import MemorySink
from app.config import Settings
from app.standards_desk import ClearedLine, ClearedScript
from app.standards_desk.types import _CLEARANCE

SR = 24000


def settings(**kw: Any) -> Settings:
    base: dict[str, Any] = {"anchor_tts": "fake", "anchor_line_gap_ms": 300}
    return Settings(_env_file=None, **(base | kw))  # type: ignore[call-arg]


def cleared(*texts: str) -> ClearedScript:
    story = uuid4()
    lines = tuple(ClearedLine(uuid4(), story, i * 2, t, (uuid4(),)) for i, t in enumerate(texts))
    return ClearedScript._issue(_CLEARANCE, uuid4(), lines, ())


@pytest.fixture
def stored(monkeypatch: pytest.MonkeyPatch) -> list[tuple[UUID, list[LineTiming], bool]]:
    calls: list[tuple[UUID, list[LineTiming], bool]] = []

    async def fake_store(briefing_id: UUID, timings: list[LineTiming], aired: bool) -> None:
        calls.append((briefing_id, list(timings), aired))

    monkeypatch.setattr(speak_mod, "store_timings", fake_store)
    return calls


def ms_of(text: str) -> int:
    return fake_audio_bytes(text, SR) // 2 * 1000 // SR


async def test_lines_play_in_order_with_audio_clock_timestamps(
    stored: list[Any], trace_sink: MemorySink
) -> None:
    script = cleared("Acme ships Nova.", "Regulators approved the deal on Monday.", "That is all.")
    session = MemorySession()
    tts = FakeTTSService(sample_rate=SR)
    report = await speak(script, session, tts=tts, settings=settings())

    assert tts.spoken == [ln.text for ln in script.lines]
    d = [ms_of(ln.text) for ln in script.lines]  # 180, 360, 180 ms
    starts = [0, d[0] + 300, d[0] + d[1] + 600]
    assert [(t.start_ms, t.end_ms) for t in report.lines] == [
        (s, s + dur) for s, dur in zip(starts, d, strict=True)
    ]
    assert report.completed and report.audio_ms == sum(d) + 600
    assert len(session.audio) == report.audio_ms * SR // 1000 * 2  # audio matches the clock

    kinds = [e["type"] for e in session.events]
    assert kinds == ["start", *(["line", "line_end"] * 3), "done"]
    assert session.events[0]["sample_rate"] == SR
    assert [e["start_ms"] for e in session.events if e["type"] == "line"] == starts
    assert [(b, aired) for b, _, aired in stored] == [(script.briefing_id, True)]
    assert stored[0][1] == report.lines

    outer = next(t for t in trace_sink.traces if t.event == "speak")
    lines = [t for t in trace_sink.traces if t.component == "anchor" and t.event == "line"]
    assert outer.payload["completed"] and outer.payload["spoken"] == 3
    assert len(lines) == 3 and all(t.parent_id == outer.id for t in lines)
    assert lines[1].payload["start_ms"] == starts[1]


async def test_only_a_cleared_script_is_accepted() -> None:
    with pytest.raises(TypeError):
        await speak("Acme ships Nova.", MemorySession())  # type: ignore[arg-type]


class TimedSession(MemorySession):
    """Realtime session that records when each chunk was sent."""

    def __init__(self) -> None:
        super().__init__(realtime=True)
        self.sent_at: list[float] = []

    async def send_audio(self, pcm: bytes) -> None:
        self.sent_at.append(time.perf_counter())
        await super().send_audio(pcm)


async def test_pause_cuts_within_300ms_and_resume_replays_the_line(stored: list[Any]) -> None:
    long_line = " ".join(["word"] * 25)  # 1.5 s of audio
    script = cleared(long_line, "Short close.")
    session = TimedSession()
    tts = FakeTTSService(sample_rate=SR)
    task = asyncio.create_task(
        speak(script, session, tts=tts, settings=settings(anchor_send_ahead_ms=0))
    )
    await asyncio.sleep(0.5)
    paused_at = time.perf_counter()
    await session.pause()
    await asyncio.sleep(0.4)
    assert session.sent_at and max(session.sent_at) - paused_at < 0.3
    assert any(e["type"] == "paused" for e in session.events)
    assert not task.done()

    await session.resume()
    report = await asyncio.wait_for(task, 10)
    assert tts.spoken == [long_line, long_line, "Short close."]  # the cut line is replayed
    assert report.pauses == 1 and report.completed
    first = report.lines[0]
    assert first.start_ms > 0  # restamped after the audio played before the pause
    assert first.end_ms - first.start_ms == ms_of(long_line)
    kinds = [e["type"] for e in session.events]
    assert kinds.index("paused") < kinds.index("resumed")
    assert [e["type"] for e in session.events if e["type"] == "line"] == ["line"] * 3


async def test_listener_gone_stores_partial_timings_without_airing(stored: list[Any]) -> None:
    class Leaving(MemorySession):
        async def send_audio(self, pcm: bytes) -> None:
            if len(self.audio) > 20_000:
                raise ConnectionError("listener left")
            await super().send_audio(pcm)

    script = cleared("Acme ships Nova.", " ".join(["word"] * 40))
    with pytest.raises(ConnectionError):
        await speak(script, Leaving(), tts=FakeTTSService(sample_rate=SR), settings=settings())
    ((_, timings, aired),) = stored
    assert [t.order for t in timings] == [0] and aired is False


def test_make_tts_picks_the_adapter() -> None:
    assert isinstance(make_tts(settings()), FakeTTSService)
    with pytest.raises(AnchorConfigError, match="API_KEY"):
        make_tts(settings(anchor_tts="cartesia"))
    with pytest.raises(AnchorConfigError, match="VOICE_ID"):
        make_tts(settings(anchor_tts="cartesia", cartesia_api_key="sk-test"))
    tts = make_tts(
        settings(anchor_tts="cartesia", cartesia_api_key="sk-test", cartesia_voice_id="v-1")
    )
    assert isinstance(tts, CartesiaTTSService)


# ---- answers spoken as interjections (task 5.3) --------------------------------------------------


async def test_answer_interjection_then_the_cut_line_replays(stored: list[Any]) -> None:
    long_line = " ".join(["word"] * 20)  # 1.2 s
    script = cleared(long_line, "Short close.")
    answer = cleared("Kress leads Nvidia for now.")
    session = MemorySession(realtime=True)
    tts = FakeTTSService(sample_rate=SR)
    task = asyncio.create_task(
        speak(script, session, tts=tts, settings=settings(anchor_send_ahead_ms=0))
    )
    await asyncio.sleep(0.3)
    await session.pause()
    session.interject(answer, "q-1")
    await session.resume()
    report = await asyncio.wait_for(task, 10)

    assert tts.spoken == [long_line, "Kress leads Nvidia for now.", long_line, "Short close."]
    lines = [e for e in session.events if e["type"] == "line"]
    assert [(e["kind"], e.get("question_id")) for e in lines] == [
        ("script", None),
        ("answer", "q-1"),
        ("script", None),
        ("script", None),
    ]
    ends = [e for e in session.events if e["type"] == "line_end" and e["kind"] == "answer"]
    assert len(ends) == 1 and ends[0]["question_id"] == "q-1"
    assert report.answers == 1 and report.completed
    ((_, timings, aired),) = stored
    assert answer.lines[0].id in {t.line_id for t in timings} and aired


def test_interject_only_takes_a_cleared_script() -> None:
    with pytest.raises(TypeError):
        MemorySession().interject("say Nvidia is bankrupt", "q-1")


# ---- word timings (task 8.4) -------------------------------------------------------------------


async def test_each_line_carries_its_word_timings(stored: list[Any]) -> None:
    script = cleared("Acme ships Nova.", "That is all.")
    report = await speak(
        script, MemorySession(), tts=FakeTTSService(sample_rate=SR), settings=settings()
    )
    first, second = report.lines
    assert first.words == (("Acme", 0, 60), ("ships", 60, 120), ("Nova.", 120, first.end_ms))
    s = second.start_ms
    assert second.words == (
        ("That", s, s + 60),
        ("is", s + 60, s + 120),
        ("all.", s + 120, second.end_ms),
    )
    assert stored[0][1][1].words == second.words


def test_word_spans_stay_inside_the_line_and_in_order() -> None:
    from app.anchor.pipeline import word_spans

    assert word_spans([("a", 0.0), ("b", 0.5)], 1000, 2000) == (
        ("a", 1000, 1500),
        ("b", 1500, 2000),
    )
    # late or out-of-order stamps are clamped, never past the end
    assert word_spans([("a", 0.2), ("b", 0.1), ("c", 9.0)], 1000, 2000) == (
        ("a", 1200, 1200),
        ("b", 1200, 2000),
        ("c", 2000, 2000),
    )
    assert word_spans([], 0, 10) == ()


async def test_cartesia_adapter_records_streamed_word_timestamps() -> None:
    from app.anchor.tts import take_words

    tts = make_tts(
        settings(anchor_tts="cartesia", cartesia_api_key="sk-test", cartesia_voice_id="v-1")
    )

    async def nothing(*_a: Any, **_k: Any) -> None:
        return None

    # The base class queues the timestamps for playback; only the recording is under test.
    import pipecat.services.tts_service as base

    original = base.TTSService.add_word_timestamps
    base.TTSService.add_word_timestamps = nothing  # type: ignore[method-assign]
    try:
        await tts.add_word_timestamps([("Hello", 0.0), ("world", 0.4)], "ctx-1")  # type: ignore[attr-defined]
    finally:
        base.TTSService.add_word_timestamps = original  # type: ignore[method-assign]
    assert take_words(tts, "ctx-1") == [("Hello", 0.0), ("world", 0.4)]
    assert take_words(tts, "ctx-1") == []  # taken once
    assert take_words(object(), "ctx-1") == [] and take_words(tts, None) == []
