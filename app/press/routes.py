"""``/press`` API for the web Press feed (task 8.2)."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.press.feed import PressCursor, PressStory, press_stories

router = APIRouter(prefix="/press", tags=["press"])


class PressPage(BaseModel):
    stories: list[PressStory]
    next: PressCursor | None  # pass as ``after_latest_at`` + ``after_id`` for the next page


@router.get("/stories")
async def list_stories(
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    after_latest_at: datetime | None = None,
    after_id: UUID | None = None,
) -> PressPage:
    """Newest stories first. Summaries come from the crawler desk and are not fact-checked."""
    if (after_latest_at is None) != (after_id is None):
        raise HTTPException(422, "after_latest_at and after_id go together")
    after = (
        PressCursor(latest_at=after_latest_at, id=after_id)
        if after_latest_at is not None and after_id is not None
        else None
    )
    stories = await press_stories(limit, after)
    last = stories[-1] if len(stories) == limit else None
    return PressPage(
        stories=stories,
        next=PressCursor(latest_at=last.latest_at, id=last.id) if last else None,
    )
