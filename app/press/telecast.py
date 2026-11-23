"""Telecasts: a reader asks to broadcast one Press story (task 8.3, decision 0027).

``start_telecast()`` records a ``telecasts`` row and runs the job in the background (this API
process, ``press_telecast_concurrency`` at a time). The job is the same path as a briefing, on one
story: ``rundown_for_story`` -> ``draft_script`` -> ``review_script`` (Editor judge and rewrites)
-> ``clear_for_air`` (Standards Desk) -> ``speak`` into a WAV file under ``media_dir``. Only cleared
lines are voiced. Each step is written to the row, so the web player can show progress.

A ready telecast of the same story younger than ``press_telecast_reuse_hours`` is reused, and so is
one still running. A row stuck in a running step for ``press_telecast_stale_minutes`` (the process
died) reads as failed.
"""

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, select, update

from app.anchor import AnchorConfigError, AnchorError, WavFileSession, speak
from app.archive import span
from app.config import get_settings
from app.db.models import Claim, ScriptLine, Telecast, utcnow
from app.db.session import get_engine, session_scope
from app.editor import review_script
from app.log import get_logger
from app.press.feed import PressStory, press_story
from app.producer import NoStoriesError, rundown_for_story
from app.shared import llm
from app.standards_desk import NotClearedError, clear_for_air
from app.writer import WriterError, draft_script

RUNNING = ("queued", "writing", "checking", "clearing", "voicing")

log = get_logger(__name__)
_telecasts = Telecast.__table__  # type: ignore[attr-defined]
_lines = ScriptLine.__table__  # type: ignore[attr-defined]
_claims = Claim.__table__  # type: ignore[attr-defined]


class StoryNotFoundError(LookupError):
    pass


class TelecastNotFoundError(LookupError):
    pass


class TelecastLine(BaseModel):
    id: UUID
    text: str
    start_ms: int
    end_ms: int


class TelecastView(BaseModel):
    id: UUID
    story_id: UUID
    briefing_id: UUID | None
    step: str  # queued | writing | checking | clearing | voicing | ready | failed
    error: str | None
    created_at: datetime
    updated_at: datetime
    audio_url: str | None = None  # same-origin path, e.g. /media/telecasts/<id>.wav
    duration_ms: int | None = None
    lines: list[TelecastLine] = []  # voiced lines with audio timings (ready only)
    verdicts: dict[str, int] = {}  # the briefing's claims by verdict
    story: PressStory | None = None


# ---- running -----------------------------------------------------------------------------------

Runner = Callable[[UUID, UUID], None]
_tasks: set[asyncio.Task[None]] = set()
_slots: asyncio.Semaphore | None = None


def media_dir() -> Path:
    return Path(get_settings().media_dir)


def audio_file(telecast_id: UUID) -> tuple[Path, str]:
    """(absolute path, path relative to media_dir) of a telecast's WAV file."""
    rel = f"telecasts/{telecast_id}.wav"
    return media_dir() / rel, rel


def schedule(telecast_id: UUID, story_id: UUID) -> None:
    """Run the job in the background of this process, a few at a time."""
    global _slots
    if _slots is None:
        _slots = asyncio.Semaphore(get_settings().press_telecast_concurrency)
    slots = _slots

    async def guarded() -> None:
        async with slots:
            await run_telecast(telecast_id, story_id)

    task = asyncio.create_task(guarded())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _set(telecast_id: UUID, **values: object) -> None:
    async with get_engine().begin() as conn:
        await conn.execute(
            update(_telecasts)
            .where(_telecasts.c.id == telecast_id)
            .values(**values, updated_at=utcnow())
        )


async def run_telecast(telecast_id: UUID, story_id: UUID) -> None:
    """The whole job. Never raises: every failure ends as ``step=failed`` with a reason."""
    settings = get_settings()
    with span("press", "telecast", telecast_id=telecast_id, story_id=story_id) as s:
        step = "writing"
        try:
            await _set(telecast_id, step=step)
            rundown = await rundown_for_story(story_id, settings.press_telecast_seconds)
            s.briefing_id = rundown.briefing_id
            await _set(telecast_id, briefing_id=rundown.briefing_id)
            script = await draft_script(rundown)
            step = "checking"
            await _set(telecast_id, step=step)
            reviewed = await review_script(script)
            step = "clearing"
            await _set(telecast_id, step=step)
            cleared = await clear_for_air(reviewed)
            step = "voicing"
            await _set(telecast_id, step=step)
            path, rel = audio_file(telecast_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            report = await speak(cleared, WavFileSession(path, settings.anchor_sample_rate))
            await _set(telecast_id, step="ready", audio_path=rel, duration_ms=report.audio_ms)
            s.set(step="ready", lines=len(report.lines), audio_ms=report.audio_ms)
        except Exception as e:
            reason = failure_reason(e)
            if reason is None:
                log.exception("press.telecast_crashed", telecast_id=str(telecast_id), step=step)
                reason = "internal error"
            await _set(telecast_id, step="failed", error=f"{step}: {reason}")
            s.set(step="failed", failed_at=step, error=reason)


def failure_reason(e: Exception) -> str | None:
    """A reader-facing reason for an expected failure; None for a bug."""
    if isinstance(e, NoStoriesError):
        return "the story no longer has enough live sources"
    if isinstance(e, WriterError):
        return "the writer could not draft this story"
    if isinstance(e, NotClearedError):
        return "nothing in this story could be verified well enough to air"
    if isinstance(e, AnchorConfigError):
        return "text-to-speech is not configured"
    if isinstance(e, AnchorError):
        return "the voice service did not finish"
    if isinstance(e, llm.LLMError):
        return "the language model was unavailable"
    return None


# ---- requests ----------------------------------------------------------------------------------


async def start_telecast(story_id: UUID, runner: Runner = schedule) -> TelecastView:
    """Reuse a recent or running telecast of the story, or start a new one."""
    if await press_story(story_id) is None:
        raise StoryNotFoundError(str(story_id))
    if (current := await reusable(story_id)) is not None:
        return await telecast_view(current)
    row = Telecast(story_id=story_id)
    async with session_scope() as session:
        session.add(row)
    runner(row.id, story_id)
    return await telecast_view(row.id)


async def reusable(story_id: UUID) -> UUID | None:
    settings = get_settings()
    now = utcnow()
    query = (
        select(_telecasts.c.id, _telecasts.c.step, _telecasts.c.audio_path, _telecasts.c.updated_at)
        .where(_telecasts.c.story_id == story_id)
        .where(
            _telecasts.c.created_at >= now - timedelta(hours=settings.press_telecast_reuse_hours)
        )
        .order_by(_telecasts.c.created_at.desc())
        .limit(5)
    )
    async with get_engine().connect() as conn:
        rows = (await conn.execute(query)).all()
    for r in rows:
        if r.step == "ready" and r.audio_path and (media_dir() / r.audio_path).is_file():
            return UUID(str(r.id))
        if r.step in RUNNING and not is_stale(r.updated_at, now):
            return UUID(str(r.id))
    return None


def is_stale(updated_at: datetime, now: datetime) -> bool:
    return now - updated_at > timedelta(minutes=get_settings().press_telecast_stale_minutes)


async def telecast_view(telecast_id: UUID) -> TelecastView:
    async with get_engine().connect() as conn:
        row = (
            await conn.execute(select(_telecasts).where(_telecasts.c.id == telecast_id))
        ).one_or_none()
        if row is None:
            raise TelecastNotFoundError(str(telecast_id))
        view = TelecastView(
            id=row.id,
            story_id=row.story_id,
            briefing_id=row.briefing_id,
            step=row.step,
            error=row.error,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        if view.step in RUNNING and is_stale(row.updated_at, utcnow()):
            view.step, view.error = "failed", f"{view.step}: interrupted (the server restarted)"
        if view.briefing_id is not None:
            counts = await conn.execute(
                select(_claims.c.verdict, func.count())
                .join(_lines, _lines.c.id == _claims.c.script_line_id)
                .where(_lines.c.briefing_id == view.briefing_id)
                .group_by(_claims.c.verdict)
            )
            view.verdicts = {str(v): int(n) for v, n in counts.all()}
        if view.step == "ready" and row.audio_path and view.briefing_id is not None:
            view.audio_url = f"/media/{row.audio_path}"
            view.duration_ms = row.duration_ms
            lines = await conn.execute(
                select(_lines.c.id, _lines.c.text, _lines.c.audio_start_ms, _lines.c.audio_end_ms)
                .where(
                    _lines.c.briefing_id == view.briefing_id,
                    _lines.c.audio_start_ms.is_not(None),
                    _lines.c.audio_end_ms.is_not(None),
                )
                .order_by(_lines.c.audio_start_ms)
            )
            view.lines = [
                TelecastLine(id=r.id, text=r.text, start_ms=r.audio_start_ms, end_ms=r.audio_end_ms)
                for r in lines.all()
            ]
    view.story = await press_story(view.story_id)
    return view


def pending_jobs() -> int:
    return len(_tasks)


async def wait_for_jobs() -> None:
    """For tests and shutdown: wait for running telecast jobs."""
    if _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)
