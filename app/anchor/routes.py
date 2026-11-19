"""Live briefing over a WebSocket (task 4.2, decision 0017).

    ws://host/anchor/briefings/{id}/live

Server -> client: binary PCM16 mono chunks and JSON events (see ``app.anchor.session``).
Client -> server: ``{"type": "pause"}`` / ``{"type": "resume"}``.
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
from app.log import get_logger
from app.standards_desk import BriefingNotFoundError, NotClearedError
from app.standards_desk import stored as stored_mod

router = APIRouter(prefix="/anchor", tags=["anchor"])
log = get_logger(__name__)


async def _controls(ws: WebSocket, session: WebSocketSession) -> None:
    """Read pause/resume messages until the client goes away."""
    while True:
        raw = await ws.receive_text()
        try:
            kind = json.loads(raw).get("type")
        except (ValueError, AttributeError):
            continue
        if kind == "pause":
            await session.pause()
        elif kind == "resume":
            await session.resume()


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
    controls = asyncio.create_task(_controls(ws, session))
    try:
        await speak(script, session)
    except AnchorConfigError as e:
        log.warning("anchor.not_configured", error=str(e))
        await ws.close(code=4500, reason="text-to-speech is not configured")
        return
    except WebSocketDisconnect:
        log.info("anchor.listener_left", briefing_id=str(briefing_id))
        return
    finally:
        controls.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await controls
    with contextlib.suppress(Exception):
        await ws.close()
