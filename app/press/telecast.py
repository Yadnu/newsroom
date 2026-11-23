"""Telecasts: a reader asks to broadcast one Press story (task 8.3, decision 0027).

``start_telecast()`` records a ``telecasts`` row and runs the job in the background: on the ARQ
worker, or in this API process when Redis is unreachable (``press_telecast_runner``, task 9.3;
``press_telecast_concurrency`` at a time either way). The job is the same path as a briefing, on one
story: ``rundown_for_story`` -> ``draft_script`` -> ``review_script`` (Editor judge and rewrites)
-> ``clear_for_air`` (Standards Desk) -> ``speak`` into a WAV file under ``media_dir``. Only cleared
lines are voiced. Each step is written to the row, so the web player can show progress.

A ready telecast of the same story younger than ``press_telecast_reuse_hours`` is reused, and so is
one still running. A row stuck in a running step for ``press_telecast_stale_minutes`` (the process
died) reads as failed.
"""

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncConnection

from app.anchor import AnchorConfigError, AnchorError, WavFileSession, speak
from app.archive import span
from app.config import get_settings
from app.db.models import Claim, ScriptLine, Telecast, utcnow
from app.db.session import get_engine
from app.editor import review_script
from app.log import get_logger
from app.press import queue
from app.press.audio import AudioEncodeError, encode_mp3, lead_ms
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


class TelecastWord(BaseModel):
    text: str
    start_ms: int
    end_ms: int


class TelecastLine(BaseModel):
    id: UUID
    text: str
    start_ms: int
    end_ms: int
    words: list[TelecastWord] = []  # from the TTS (task 8.4); empty if it gave none


def words_of(raw: object) -> list[TelecastWord]:
    """``script_lines.audio_words`` ([[word, start, end], ...]) -> words; tolerant of bad rows."""
    out: list[TelecastWord] = []
    if isinstance(raw, list):
        for w in raw:
            if isinstance(w, list) and len(w) == 3 and isinstance(w[0], str):
                try:
                    out.append(TelecastWord(text=w[0], start_ms=int(w[1]), end_ms=int(w[2])))
                except (TypeError, ValueError):
                    continue
    return out


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
    audio_lead_ms: int = 0  # silence at the start of the file (MP3 encoder delay, task 9.4)
    lines: list[TelecastLine] = []  # voiced lines with audio timings (ready only)
    verdicts: dict[str, int] = {}  # the briefing's claims by verdict
    story: PressStory | None = None


# ---- running -----------------------------------------------------------------------------------

Runner = Callable[[UUID, UUID], Awaitable[None] | None]
_tasks: set[asyncio.Task[None]] = set()
_slots: asyncio.Semaphore | None = None


def media_dir() -> Path:
    return Path(get_settings().media_dir)


def audio_file(telecast_id: UUID) -> tuple[Path, str]:
    """(absolute path, path relative to media_dir) of the WAV the Anchor writes (then MP3)."""
    rel = f"telecasts/{telecast_id}.wav"
    return media_dir() / rel, rel


async def dispatch(telecast_id: UUID, story_id: UUID) -> None:
    """Run the job where ``press_telecast_runner`` says (task 9.3): the ARQ worker, falling back to
    this process when Redis is unreachable (``auto``), or in this process (``inprocess``)."""
    mode = get_settings().press_telecast_runner
    if mode != "inprocess" and await queue.enqueue_telecast(
        telecast_id, story_id, need_worker=mode == "auto"
    ):
        return
    if mode == "worker":
        await _set(telecast_id, step="failed", error="queued: the worker queue is unavailable")
        return
    schedule(telecast_id, story_id)


def to_mp3(wav: Path, rel: str) -> str:
    """Encode the telecast's WAV to MP3 and remove the WAV (task 9.4). On failure keep the WAV: the
    telecast still airs. Returns the audio path relative to media_dir."""
    mp3 = wav.with_suffix(".mp3")
    try:
        encode_mp3(wav, mp3)
    except AudioEncodeError as e:
        log.warning("press.mp3_failed", error=str(e)[:200])
        return rel
    wav.unlink(missing_ok=True)
    return rel.removesuffix(".wav") + ".mp3"


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
            rel = await asyncio.to_thread(to_mp3, path, rel)
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


async def start_telecast(story_id: UUID, runner: Runner | None = None) -> TelecastView:
    """Reuse a recent or running telecast of the story, or start a new one."""
    if await press_story(story_id) is None:
        raise StoryNotFoundError(str(story_id))
    # One request at a time per story decides reuse-or-create (two tabs, or React running an effect
    # twice in development, must not start two jobs): a transaction-scoped advisory lock.
    async with get_engine().begin() as conn:
        await conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
            {"k": f"telecast:{story_id}"},
        )
        current = await reusable(story_id, conn)
        if current is None:
            now = utcnow()
            new_id = uuid4()
            await conn.execute(
                insert(_telecasts).values(
                    id=new_id, story_id=story_id, step="queued", created_at=now, updated_at=now
                )
            )
    if current is not None:
        return await telecast_view(current)
    started = (runner or dispatch)(new_id, story_id)
    if inspect.isawaitable(started):
        await started
    return await telecast_view(new_id)


async def reusable(story_id: UUID, conn: AsyncConnection | None = None) -> UUID | None:
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
    if conn is None:
        async with get_engine().connect() as own:
            rows = (await own.execute(query)).all()
    else:
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
            view.audio_lead_ms = lead_ms(row.audio_path, get_settings().anchor_sample_rate)
            view.duration_ms = row.duration_ms
            lines = await conn.execute(
                select(
                    _lines.c.id,
                    _lines.c.text,
                    _lines.c.audio_start_ms,
                    _lines.c.audio_end_ms,
                    _lines.c.audio_words,
                )
                .where(
                    _lines.c.briefing_id == view.briefing_id,
                    _lines.c.audio_start_ms.is_not(None),
                    _lines.c.audio_end_ms.is_not(None),
                )
                .order_by(_lines.c.audio_start_ms)
            )
            view.lines = [
                TelecastLine(
                    id=r.id,
                    text=r.text,
                    start_ms=r.audio_start_ms,
                    end_ms=r.audio_end_ms,
                    words=words_of(r.audio_words),
                )
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


async def transcode_existing(dry_run: bool = False) -> tuple[int, int]:
    """Convert ready telecasts stored as WAV to MP3 (task 9.4). Returns (converted, bytes saved)."""
    query = select(_telecasts.c.id, _telecasts.c.audio_path).where(
        _telecasts.c.step == "ready", _telecasts.c.audio_path.like("%.wav")
    )
    async with get_engine().connect() as conn:
        rows = (await conn.execute(query)).all()
    converted = saved = 0
    for r in rows:
        wav = media_dir() / str(r.audio_path)
        if not wav.is_file():
            continue
        before = wav.stat().st_size
        if dry_run:
            converted += 1
            saved += before * 5 // 6  # about six times smaller
            continue
        rel = await asyncio.to_thread(to_mp3, wav, str(r.audio_path))
        if rel.endswith(".mp3"):
            converted += 1
            saved += before - (media_dir() / rel).stat().st_size
            async with get_engine().begin() as conn:
                await conn.execute(
                    update(_telecasts).where(_telecasts.c.id == r.id).values(audio_path=rel)
                )
    return converted, saved
