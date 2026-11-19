"""Live briefing over a WebSocket (task 4.2, decision 0017).

    ws://host/anchor/briefings/{id}/live

Server -> client: binary PCM16 mono chunks and JSON events (see ``app.anchor.session``).
Client -> server: ``{"type": "pause"}`` / ``{"type": "resume"}``, and push-to-talk mic audio
(``mic_start``, binary PCM16 chunks, ``mic_end``) handled by ``app.caller.live.CallIn``.
Close codes: 4404 unknown briefing, 4409 nothing cleared for air, 4500 TTS not configured.
"""

import asyncio
import contextlib
import json
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.anchor.pipeline import speak
from app.anchor.session import WebSocketSession
from app.anchor.tts import AnchorConfigError
from app.caller.live import CallIn
from app.log import get_logger
from app.standards_desk import BriefingNotFoundError, NotClearedError
from app.standards_desk import stored as stored_mod

router = APIRouter(prefix="/anchor", tags=["anchor"])
log = get_logger(__name__)


CALLER_DRAIN_S = 20.0  # after the briefing ends, let a question in flight finish


async def _controls(ws: WebSocket, session: WebSocketSession, callin: CallIn) -> None:
    """Read control messages and mic audio until the client goes away."""
    while True:
        msg = await ws.receive()
        if msg["type"] == "websocket.disconnect":
            raise WebSocketDisconnect(msg.get("code", 1000))
        if msg.get("bytes") is not None:
            callin.audio(msg["bytes"])
            continue
        try:
            data = json.loads(msg.get("text") or "")
            kind = data.get("type")
        except (ValueError, AttributeError):
            continue
        if kind == "pause":
            await session.pause()
        elif kind == "resume":
            await session.resume()
        elif kind == "mic_start":
            rate = data.get("sample_rate")
            await callin.start(rate if isinstance(rate, int) else None)
        elif kind == "mic_end":
            await callin.end()


@router.websocket("/briefings/{briefing_id}/live")
async def live(ws: WebSocket, briefing_id: UUID) -> None:
    await ws.accept()
    try:
        script = await stored_mod.clear_stored(briefing_id)
    except BriefingNotFoundError:
        await ws.close(code=4404, reason="unknown briefing")
        return
    except NotClearedError:
        await ws.close(code=4409, reason="nothing cleared for air")
        return
    session = WebSocketSession(ws)
    callin = CallIn(script, session.send_event, lambda: session.current_line_id)
    controls = asyncio.create_task(_controls(ws, session, callin))
    try:
        await speak(script, session)
        await callin.wait(CALLER_DRAIN_S)
    except AnchorConfigError as e:
        log.warning("anchor.not_configured", error=str(e))
        await ws.close(code=4500, reason="text-to-speech is not configured")
        return
    except WebSocketDisconnect:
        log.info("anchor.listener_left", briefing_id=str(briefing_id))
        return
    finally:
        await callin.close()
        controls.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await controls
    with contextlib.suppress(Exception):
        await ws.close()
