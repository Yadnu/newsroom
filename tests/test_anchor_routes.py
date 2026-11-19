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
