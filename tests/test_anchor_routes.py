"""WebSocket /anchor/briefings/{id}/live with the fake TTS (task 4.2)."""

import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import app.anchor.pipeline as pipeline
import app.anchor.routes as routes
from app.anchor import FakeTTSService, VoiceSession
from app.anchor.pipeline import SpeakReport
from app.config import Settings
from app.main import app
from app.standards_desk import BriefingNotFoundError, ClearedLine, ClearedScript, NotClearedError
from app.standards_desk.types import _CLEARANCE

SETTINGS = Settings(_env_file=None, anchor_tts="fake", anchor_send_ahead_ms=10_000)  # type: ignore[call-arg]


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"stored": []}
    story = uuid4()
    script = ClearedScript._issue(
        _CLEARANCE,
        uuid4(),
        (
            ClearedLine(uuid4(), story, 0, "Acme ships Nova.", (uuid4(),)),
            ClearedLine(uuid4(), story, 1, "That is all.", (uuid4(),)),
        ),
        (),
    )
    state["script"] = script

    async def fake_clear(briefing_id: UUID) -> ClearedScript:
        if state.get("missing"):
            raise BriefingNotFoundError("no briefing")
        if state.get("nothing"):
            raise NotClearedError("all blocked")
        return script

    async def fake_speak(s: ClearedScript, session: VoiceSession) -> SpeakReport:
        return await pipeline.speak(
            s,
            session,
            tts=FakeTTSService(sample_rate=24000),
            settings=state.get("settings", SETTINGS),
        )

    async def fake_store(briefing_id: UUID, timings: Any, aired: bool) -> None:
        state["stored"].append((briefing_id, timings, aired))

    monkeypatch.setattr(routes.stored_mod, "clear_stored", fake_clear)
    monkeypatch.setattr(routes, "speak", fake_speak)
    monkeypatch.setattr(pipeline, "store_timings", fake_store)
    return state


def _drain(ws: Any) -> tuple[list[dict[str, Any]], int]:
    events: list[dict[str, Any]] = []
    audio = 0
    while True:
        msg = ws.receive()
        if msg["type"] == "websocket.close":
            break
        if msg.get("bytes") is not None:
            audio += len(msg["bytes"])
        elif msg.get("text") is not None:
            events.append(json.loads(msg["text"]))
            if events[-1]["type"] == "done":
                break
    return events, audio


def test_live_streams_events_and_pcm(wired: dict[str, Any]) -> None:
    script = wired["script"]
    with TestClient(app).websocket_connect(f"/anchor/briefings/{script.briefing_id}/live") as ws:
        events, audio = _drain(ws)
    assert [e["type"] for e in events] == ["start", "line", "line_end", "line", "line_end", "done"]
    assert events[1]["line_id"] == str(script.lines[0].id) and events[1]["start_ms"] == 0
    assert events[-1]["completed"] is True
    assert audio == events[-1]["audio_ms"] * 24000 // 1000 * 2
    assert wired["stored"] and wired["stored"][0][2] is True  # aired


def test_pause_and_resume_messages(wired: dict[str, Any]) -> None:
    script = wired["script"]
    wired["settings"] = SETTINGS.model_copy(update={"anchor_send_ahead_ms": 0})  # real-time pace
    with TestClient(app).websocket_connect(f"/anchor/briefings/{script.briefing_id}/live") as ws:
        first = ws.receive_json()
        assert first["type"] == "start"
        ws.send_text(json.dumps({"type": "pause"}))
        ws.send_text("not json")  # ignored
        ws.send_text(json.dumps({"type": "resume"}))
        events, _ = _drain(ws)
    kinds = [e["type"] for e in events]
    assert "paused" in kinds and "resumed" in kinds and kinds[-1] == "done"
    assert events[-1]["completed"] is True


@pytest.mark.parametrize(("flag", "code"), [("missing", 4404), ("nothing", 4409)])
def test_close_codes(wired: dict[str, Any], flag: str, code: int) -> None:
    wired[flag] = True
    with (
        TestClient(app).websocket_connect(f"/anchor/briefings/{uuid4()}/live") as ws,
        pytest.raises(WebSocketDisconnect) as e,
    ):
        ws.receive_json()
    assert e.value.code == code


# ---- push-to-talk (task 5.1) -----------------------------------------------------------------


@pytest.fixture
def mic(wired: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    import app.caller.live as live
    from app.caller import CallerContext, FakeSTTService, Intent, StoryRef
    from app.caller import listen as real_listen

    script = wired["script"]
    story = script.lines[0].story_id
    seen: dict[str, Any] = {"contexts": []}

    async def fake_context(s: ClearedScript, current: Any = None) -> CallerContext:
        return CallerContext(s.briefing_id, (StoryRef(story, "Acme chip"),), current)

    async def classifier(transcript: str, context: CallerContext) -> Intent:
        seen["contexts"].append(context)
        return Intent("follow_up", story, f"When does {transcript}?")

    def fake_listen(chunks: Any, context: CallerContext, settings: Any = None) -> Any:
        stt = FakeSTTService(["nova ship"], sample_rate=16000)
        caller_settings = Settings(  # type: ignore[call-arg]
            _env_file=None, caller_stt="fake", caller_finalize_wait_ms=100
        )
        return real_listen(
            chunks, context, stt=stt, settings=caller_settings, classifier=classifier
        )

    monkeypatch.setattr(live, "context_for", fake_context)
    monkeypatch.setattr(live, "listen", fake_listen)
    import app.caller.pipeline as listen_mod
    from app.standards_desk import ScreenResult

    async def screen(transcript: str, intent: str | None = None) -> ScreenResult:
        return (
            ScreenResult(False, "injection", "tries to instruct", "rules")
            if "ignore" in transcript
            else ScreenResult(True, "ok", "", "llm")
        )

    monkeypatch.setattr(listen_mod, "screen_caller", screen)
    wired["settings"] = SETTINGS.model_copy(update={"anchor_send_ahead_ms": 0})  # real-time pace
    return seen


def _until(ws: Any, kind: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    while True:
        msg = ws.receive()
        if msg["type"] == "websocket.close":
            return events
        if msg.get("text") is not None:
            events.append(json.loads(msg["text"]))
            if events[-1]["type"] == kind:
                return events


def test_push_to_talk_gives_interim_then_classified_question(
    wired: dict[str, Any], mic: dict[str, Any]
) -> None:
    script = wired["script"]
    with TestClient(app).websocket_connect(f"/anchor/briefings/{script.briefing_id}/live") as ws:
        _until(ws, "line")  # the Anchor is reading line 0
        ws.send_text(json.dumps({"type": "mic_start", "sample_rate": 16000}))
        for _ in range(10):
            ws.send_bytes(b"\x01\x00" * 1600)  # 10 x 100 ms
        ws.send_text(json.dumps({"type": "mic_end"}))
        events = _until(ws, "caller_question")
        _until(ws, "done")
    interims = [e["text"] for e in events if e["type"] == "caller_interim"]
    (q,) = [e for e in events if e["type"] == "caller_question"]
    assert interims and interims[-1] == "nova ship"
    assert q["transcript"] == "nova ship" and q["intent"] == "follow_up"
    assert q["story_title"] == "Acme chip" and q["restated"] == "When does nova ship?"
    assert (q["allowed"], q["screen_category"]) == (True, "ok")
    assert mic["contexts"][0].current_story_id == script.lines[0].story_id


def test_mic_audio_without_start_is_ignored(wired: dict[str, Any], mic: dict[str, Any]) -> None:
    script = wired["script"]
    with TestClient(app).websocket_connect(f"/anchor/briefings/{script.briefing_id}/live") as ws:
        ws.send_bytes(b"\x01\x00" * 16000)
        ws.send_text(json.dumps({"type": "mic_end"}))
        events = _until(ws, "done")
    assert not [e for e in events if e["type"].startswith("caller_")]


def test_wrong_mic_rate_is_refused(wired: dict[str, Any], mic: dict[str, Any]) -> None:
    script = wired["script"]
    with TestClient(app).websocket_connect(f"/anchor/briefings/{script.briefing_id}/live") as ws:
        ws.send_text(json.dumps({"type": "mic_start", "sample_rate": 48000}))
        # Read to the end: leaving while Pipecat is still starting makes TestClient cancel the
        # app mid-startup, which a real server (uvicorn) never does on disconnect.
        events = _until(ws, "done")
    (err,) = [e for e in events if e["type"] == "caller_error"]
    assert "16000 Hz" in err["message"]
