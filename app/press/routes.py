"""``/press`` API for the web Press feed (task 8.2)."""

import asyncio
import contextlib
import json
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.caller.live import CallIn
from app.press import questions
from app.press import telecast as tc
from app.press.feed import CategoryCount, PressCursor, PressStory, press_categories, press_stories
from app.standards_desk import BriefingNotFoundError, NotClearedError

router = APIRouter(prefix="/press", tags=["press"])


class PressPage(BaseModel):
    stories: list[PressStory]
    next: PressCursor | None  # pass as ``after_latest_at`` + ``after_id`` for the next page


@router.get("/stories")
async def list_stories(
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    after_latest_at: datetime | None = None,
    after_id: UUID | None = None,
    category: Annotated[str | None, Query(max_length=30)] = None,
) -> PressPage:
    """Newest stories first. Summaries come from the crawler desk and are not fact-checked."""
    if (after_latest_at is None) != (after_id is None):
        raise HTTPException(422, "after_latest_at and after_id go together")
    after = (
        PressCursor(latest_at=after_latest_at, id=after_id)
        if after_latest_at is not None and after_id is not None
        else None
    )
    stories = await press_stories(limit, after, category=category)
    last = stories[-1] if len(stories) == limit else None
    return PressPage(
        stories=stories,
        next=PressCursor(latest_at=last.latest_at, id=last.id) if last else None,
    )


@router.get("/categories")
async def list_categories() -> list[CategoryCount]:
    """Categories with feed stories, most first (task 9.5). The web bar shows them when 2+ exist."""
    return await press_categories()


@router.post("/stories/{story_id}/telecast", status_code=202)
async def request_telecast(story_id: UUID) -> tc.TelecastView:
    """Broadcast one story: written, fact-checked, cleared and voiced in the background. Returns
    a recent or running telecast of the story if any. Poll ``GET /press/telecasts/{id}``."""
    try:
        return await tc.start_telecast(story_id)
    except tc.StoryNotFoundError as e:
        raise HTTPException(404, "unknown story, or fewer than 2 live sources") from e


@router.get("/telecasts/{telecast_id}")
async def get_telecast(telecast_id: UUID) -> tc.TelecastView:
    """Progress (``step``), and when ``ready`` the audio URL, line timings and verdict counts."""
    try:
        return await tc.telecast_view(telecast_id)
    except tc.TelecastNotFoundError as e:
        raise HTTPException(404, "unknown telecast") from e


@router.websocket("/telecasts/{telecast_id}/questions")
async def telecast_questions(ws: WebSocket, telecast_id: UUID) -> None:
    """Ask during a telecast (task 9.6, decision 0031). Client -> server: ``{"type": "ask",
    "text": "..."}``, or push-to-talk ``mic_start{sample_rate}`` + binary PCM16 + ``mic_end``.
    Server -> client: ``caller_interim``, ``caller_question``, ``caller_error``, ``answer_status``
    (see ``app.press.questions``). One question at a time. Close codes: 4404 unknown telecast,
    4409 not ready (nothing aired to ask about)."""
    await ws.accept()
    try:
        script, story_id = await questions.telecast_script(telecast_id)
    except tc.TelecastNotFoundError:
        await ws.close(code=4404, reason="unknown telecast")
        return
    except (questions.TelecastNotReadyError, BriefingNotFoundError, NotClearedError):
        await ws.close(code=4409, reason="telecast not ready")
        return
    lock = asyncio.Lock()

    async def send(event: dict[str, Any]) -> None:
        async with lock:
            await ws.send_json(event)

    callin = CallIn(
        script,
        send,
        lambda: None,
        default_story=story_id,
        on_question=lambda q: questions.answer_on_telecast(q, script, send),
    )
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                callin.audio(msg["bytes"])
                continue
            try:
                data = json.loads(msg.get("text") or "")
                kind = data.get("type")
            except (ValueError, AttributeError):
                continue
            if kind == "ask" and isinstance(data.get("text"), str):
                await callin.ask(data["text"])
            elif kind == "mic_start":
                rate = data.get("sample_rate")
                await callin.start(rate if isinstance(rate, int) else None)
            elif kind == "mic_end":
                await callin.end()
    except WebSocketDisconnect:
        pass
    finally:
        await callin.close()
    with contextlib.suppress(Exception):
        await ws.close()
