"""Questions during a telecast (task 9.6): typed and spoken, answered, voiced, declined."""

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

import app.caller.live as live
import app.press.questions as questions
from app.anchor import AnchorConfigError, LineTiming, SpeakReport
from app.caller.ask import MAX_TYPED_CHARS, clean_typed, question_from_text
from app.caller.live import CallIn
from app.caller.types import CallerContext, CallerQuestion, Intent, Interim, StoryRef
from app.main import app
from app.press.telecast import TelecastNotFoundError
from app.producer.answer import AnswerResult
from app.standards_desk import ClearedLine, ClearedScript
from app.standards_desk.screen import ScreenResult
from app.standards_desk.types import _CLEARANCE

STORY = uuid4()
OK = ScreenResult(True, "ok", "", "rules")


def cleared(*texts: str, briefing: UUID | None = None) -> ClearedScript:
    return ClearedScript._issue(
        _CLEARANCE,
        briefing or uuid4(),
        tuple(ClearedLine(uuid4(), STORY, i, t, (uuid4(),)) for i, t in enumerate(texts)),
        (),
    )


SCRIPT = cleared("Acme ships Nova.", "That is all.")


def question(intent: str = "follow_up", screen: ScreenResult | None = OK) -> CallerQuestion:
    return CallerQuestion("When does Nova ship?", intent, STORY, "When does Nova ship?", screen)  # type: ignore[arg-type]


# ---- typed questions (caller) --------------------------------------------------------------------


def test_clean_typed_collapses_whitespace_and_caps_length() -> None:
    assert clean_typed("  when\n does   it ship? ") == "when does it ship?"
    assert len(clean_typed("word " * 400)) <= MAX_TYPED_CHARS


async def test_question_from_text_classifies_and_screens() -> None:
    context = CallerContext(uuid4(), (StoryRef(STORY, "Acme Nova"),), STORY)
    seen: dict[str, Any] = {}

    async def classifier(text: str, ctx: CallerContext) -> Intent:
        seen["classified"] = (text, ctx.current_story_id)
        return Intent("follow_up", STORY, "When does Acme ship Nova?")

    async def screener(text: str, intent: str | None) -> ScreenResult:
        seen["screened"] = (text, intent)
        return OK

    q = await question_from_text(
        " when does  it ship ", context, classifier=classifier, screener=screener
    )
    assert (q.transcript, q.intent, q.story_id) == ("when does it ship", "follow_up", STORY)
    assert q.restated == "When does Acme ship Nova?" and q.screen == OK
    assert seen == {
        "classified": ("when does it ship", STORY),
        "screened": ("when does it ship", "follow_up"),
    }


async def _callin(sent: list[dict[str, Any]], **kw: Any) -> CallIn:
    async def send(e: dict[str, Any]) -> None:
        sent.append(e)

    callin = CallIn(SCRIPT, send, lambda: None, default_story=STORY, **kw)
    callin._context = CallerContext(SCRIPT.briefing_id, (StoryRef(STORY, "Acme Nova"),))
    return callin


async def test_callin_ask_hands_a_typed_question_on_and_takes_one_at_a_time() -> None:
    sent: list[dict[str, Any]] = []
    handed: list[CallerQuestion] = []
    contexts: list[CallerContext] = []

    async def asker(text: str, ctx: CallerContext) -> CallerQuestion:
        contexts.append(ctx)
        return question()

    async def on_question(q: CallerQuestion) -> None:
        handed.append(q)

    callin = await _callin(sent, asker=asker, on_question=on_question)
    await callin.ask("When does Nova ship?")
    await callin.ask("And the price?")  # still busy with the first
    await callin.wait(2)
    assert [e["type"] for e in sent] == ["caller_error", "caller_question"]
    assert sent[0]["message"] == "one question at a time"
    assert sent[1]["story_title"] == "Acme Nova" and sent[1]["allowed"] is True
    assert len(handed) == 1
    assert contexts[0].current_story_id == STORY  # no line playing: the telecast's story

    await callin.ask("   ")  # nothing typed: ignored
    assert not callin.busy


async def test_callin_ask_reports_a_failed_classify() -> None:
    sent: list[dict[str, Any]] = []

    async def asker(text: str, ctx: CallerContext) -> CallerQuestion:
        raise RuntimeError("boom")

    callin = await _callin(sent, asker=asker)
    await callin.ask("When does Nova ship?")
    await callin.wait(2)
    assert sent == [{"type": "caller_error", "message": "could not process the question"}]


# ---- answering (press) ---------------------------------------------------------------------------


def _recorder() -> tuple[list[dict[str, Any]], Any]:
    sent: list[dict[str, Any]] = []

    async def send(e: dict[str, Any]) -> None:
        sent.append(e)

    return sent, send


def _answer(answer: ClearedScript, fallback: bool = False) -> Any:
    async def answerer(q: CallerQuestion, s: ClearedScript) -> AnswerResult:
        assert s is SCRIPT
        return AnswerResult(answer, fallback, 1234)

    return answerer


async def test_declines_off_topic_and_blocked_questions_without_answering() -> None:
    async def answerer(q: CallerQuestion, s: ClearedScript) -> AnswerResult:
        raise AssertionError("must not answer")

    for q in (question("off_topic"), question(screen=ScreenResult(False, "abusive", "", "rules"))):
        sent, send = _recorder()
        await questions.answer_on_telecast(q, SCRIPT, send, answerer=answerer)
        assert sent == [{"type": "answer_status", "question_id": str(q.id), "state": "declined"}]


async def test_answer_is_voiced_with_line_timings(tmp_path: Path) -> None:
    answer = cleared("Nova ships in March.", "Acme said so on Monday.", briefing=SCRIPT.briefing_id)
    voiced: list[Path] = []

    async def voicer(s: ClearedScript, path: Path) -> SpeakReport:
        voiced.append(path)
        a, b = s.lines
        return SpeakReport(
            s.briefing_id,
            [
                LineTiming(a.id, 0, 0, 900, (("Nova", 0, 300),)),
                LineTiming(b.id, 1, 1200, 2000),
            ],
            audio_ms=2000,
            completed=True,
        )

    q = question()
    sent, send = _recorder()
    await questions.answer_on_telecast(q, SCRIPT, send, answerer=_answer(answer), voicer=voicer)
    thinking, done = sent
    assert thinking == {"type": "answer_status", "question_id": str(q.id), "state": "thinking"}
    assert done["state"] == "answering" and done["total_ms"] == 1234
    assert done["audio_url"] == f"/media/answers/{q.id}.wav" and done["duration_ms"] == 2000
    assert voiced[0].as_posix().endswith(f"answers/{q.id}.wav")
    assert done["lines"] == [
        {
            "line_id": str(answer.lines[0].id),
            "text": "Nova ships in March.",
            "start_ms": 0,
            "end_ms": 900,
            "words": [["Nova", 0, 300]],
        },
        {
            "line_id": str(answer.lines[1].id),
            "text": "Acme said so on Monday.",
            "start_ms": 1200,
            "end_ms": 2000,
            "words": [],
        },
    ]


async def test_unvoiced_answer_still_arrives_as_captions() -> None:
    async def voicer(s: ClearedScript, path: Path) -> SpeakReport:
        raise AnchorConfigError("no key")

    sent, send = _recorder()
    safe = cleared("I can't confirm more on that from our sources yet.")
    await questions.answer_on_telecast(
        question(), SCRIPT, send, answerer=_answer(safe, fallback=True), voicer=voicer
    )
    done = sent[-1]
    assert done["state"] == "unsure" and done["audio_url"] is None and done["duration_ms"] is None
    assert done["lines"][0]["start_ms"] is None


async def test_a_crashed_answer_reports_failed() -> None:
    async def answerer(q: CallerQuestion, s: ClearedScript) -> AnswerResult:
        raise RuntimeError("db down")

    sent, send = _recorder()
    await questions.answer_on_telecast(question(), SCRIPT, send, answerer=answerer)
    assert [e["state"] for e in sent] == ["thinking", "failed"]


# ---- the WebSocket ------------------------------------------------------------------------------


@pytest.fixture
def ws_wired(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"asked": []}

    async def fake_script(telecast_id: UUID) -> tuple[ClearedScript, UUID]:
        if state.get("missing"):
            raise TelecastNotFoundError(str(telecast_id))
        if state.get("not_ready"):
            raise questions.TelecastNotReadyError(str(telecast_id))
        return SCRIPT, STORY

    async def fake_ask(text: str, ctx: CallerContext) -> CallerQuestion:
        state["asked"].append((text, ctx.current_story_id))
        return question("off_topic" if "weather" in text else "follow_up")

    async def fake_answer(q: CallerQuestion, s: ClearedScript) -> AnswerResult:
        return AnswerResult(cleared("Nova ships in March."), False, 50)

    async def fake_voice(s: ClearedScript, path: Path) -> SpeakReport:
        return SpeakReport(s.briefing_id, [LineTiming(s.lines[0].id, 0, 0, 800)], audio_ms=800)

    async def fake_context(script: ClearedScript, current: UUID | None = None) -> CallerContext:
        return CallerContext(script.briefing_id, (StoryRef(STORY, "Acme Nova"),))

    monkeypatch.setattr(questions, "telecast_script", fake_script)
    monkeypatch.setattr(questions, "answer_question", fake_answer)
    monkeypatch.setattr(questions, "voice_answer", fake_voice)
    monkeypatch.setattr(live, "question_from_text", fake_ask)
    monkeypatch.setattr(live, "context_for", fake_context)
    return state


def _events_until(ws: Any, last_states: set[str]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    while True:
        e = json.loads(ws.receive_text())
        events.append(e)
        if e["type"] == "answer_status" and e["state"] in last_states:
            return events


def test_typed_question_gets_a_voiced_answer(ws_wired: dict[str, Any]) -> None:
    with TestClient(app).websocket_connect(f"/press/telecasts/{uuid4()}/questions") as ws:
        ws.send_text(json.dumps({"type": "ask", "text": "When does Nova ship?"}))
        events = _events_until(ws, {"answering", "unsure", "failed"})
        assert [e["type"] for e in events] == ["caller_question", "answer_status", "answer_status"]
        assert [e.get("state") for e in events[1:]] == ["thinking", "answering"]
        assert events[-1]["audio_url"].startswith("/media/answers/")
        ws.send_text(json.dumps({"type": "ask", "text": "And the weather tomorrow?"}))
        events = _events_until(ws, {"declined"})
        assert events[-1]["state"] == "declined"
    assert ws_wired["asked"] == [
        ("When does Nova ship?", STORY),
        ("And the weather tomorrow?", STORY),
    ]


def test_spoken_question_streams_interims_then_answers(
    ws_wired: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    got: list[int] = []

    async def fake_listen(
        audio: AsyncIterator[bytes], context: CallerContext, **kw: Any
    ) -> AsyncIterator[Any]:
        async for chunk in audio:
            got.append(len(chunk))
        yield Interim("When does")
        yield question()

    monkeypatch.setattr(live, "listen", fake_listen)
    with TestClient(app).websocket_connect(f"/press/telecasts/{uuid4()}/questions") as ws:
        ws.send_text(json.dumps({"type": "mic_start", "sample_rate": 16000}))
        ws.send_bytes(b"\x00\x00" * 160)
        ws.send_text(json.dumps({"type": "mic_end"}))
        events = _events_until(ws, {"answering"})
    assert [e["type"] for e in events][:2] == ["caller_interim", "caller_question"]
    assert got == [320]


@pytest.mark.parametrize(("flag", "code"), [("missing", 4404), ("not_ready", 4409)])
def test_unknown_or_unready_telecast_closes(ws_wired: dict[str, Any], flag: str, code: int) -> None:
    ws_wired[flag] = True
    with TestClient(app).websocket_connect(f"/press/telecasts/{uuid4()}/questions") as ws:
        msg = ws.receive()
    assert msg["type"] == "websocket.close" and msg["code"] == code


async def test_push_to_talk_with_no_words_says_so() -> None:
    sent: list[dict[str, Any]] = []

    async def silent(
        audio: AsyncIterator[bytes], ctx: CallerContext, **kw: Any
    ) -> AsyncIterator[Any]:
        async for _ in audio:
            pass
        return
        yield  # an async generator that yields nothing

    callin = await _callin(sent, listener=silent)
    await callin.start(16000)
    callin.audio(b"\x00\x00" * 160)
    await callin.end()
    await callin.wait(2)
    assert sent == [{"type": "caller_error", "message": "did not catch a question"}]
