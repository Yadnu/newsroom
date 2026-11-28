"""Questions during a telecast (task 9.6, decision 0031).

A reader watching a telecast asks by voice (push-to-talk) or by typing. The question goes through
the same desks as on a live briefing: Caller (STT, classify) -> Standards Desk (``screen_caller``)
-> Producer (``answer_question``: sources, Writer, Editor judge, ``clear_for_air``). Only then is
the cleared answer voiced, into a short WAV under ``media_dir/answers/``, and sent to the browser,
which pauses the telecast, plays the answer and resumes.

Answer audio is not referenced by any row: ``cleanup_media`` removes it as an orphan after an hour.
"""

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.anchor import AnchorConfigError, AnchorError, SpeakReport, WavFileSession, speak
from app.caller.types import CallerQuestion
from app.config import get_settings
from app.db.models import Telecast
from app.db.session import get_engine
from app.log import get_logger
from app.press.telecast import TelecastNotFoundError, media_dir
from app.producer.answer import ANSWERED_INTENTS, AnswerResult, answer_question
from app.standards_desk import ClearedScript
from app.standards_desk import stored as stored_mod

ANSWER_SUBDIR = "answers"

Send = Callable[[dict[str, Any]], Awaitable[None]]
Answerer = Callable[[CallerQuestion, ClearedScript], Awaitable[AnswerResult]]
Voicer = Callable[[ClearedScript, Path], Awaitable[SpeakReport]]

log = get_logger(__name__)
_telecasts = Telecast.__table__  # type: ignore[attr-defined]


class TelecastNotReadyError(LookupError):
    """The telecast exists but has no aired script to ask about (still running, failed, expired)."""


async def telecast_script(telecast_id: UUID) -> tuple[ClearedScript, UUID]:
    """The telecast's cleared script (what the reader heard) and its story."""
    async with get_engine().connect() as conn:
        row = (
            await conn.execute(
                select(_telecasts.c.step, _telecasts.c.briefing_id, _telecasts.c.story_id).where(
                    _telecasts.c.id == telecast_id
                )
            )
        ).one_or_none()
    if row is None:
        raise TelecastNotFoundError(str(telecast_id))
    if row.step != "ready" or row.briefing_id is None:
        raise TelecastNotReadyError(str(telecast_id))
    script = await stored_mod.clear_stored(row.briefing_id)
    return script, UUID(str(row.story_id))


def answer_file(question_id: UUID) -> tuple[Path, str]:
    """(absolute path, URL path) of a question's answer audio."""
    rel = f"{ANSWER_SUBDIR}/{question_id}.wav"
    return media_dir() / rel, f"/media/{rel}"


async def voice_answer(cleared: ClearedScript, path: Path) -> SpeakReport:
    path.parent.mkdir(parents=True, exist_ok=True)
    return await speak(cleared, WavFileSession(path, get_settings().anchor_sample_rate))


async def answer_on_telecast(
    question: CallerQuestion,
    script: ClearedScript,
    send: Send,
    *,
    answerer: Answerer | None = None,
    voicer: Voicer | None = None,
) -> None:
    """Answer an allowed follow-up or background question; decline anything else. Sends
    ``answer_status`` events: ``thinking``, then ``answering`` | ``unsure`` (the safe line) with
    the lines, their audio timings and ``audio_url`` (null if voicing failed: captions only), or
    ``declined`` | ``failed``. Never raises."""
    qid = str(question.id)
    allowed = question.screen is None or question.screen.allowed
    if not allowed or question.intent not in ANSWERED_INTENTS:
        await send({"type": "answer_status", "question_id": qid, "state": "declined"})
        return
    await send({"type": "answer_status", "question_id": qid, "state": "thinking"})
    try:
        result = await (answerer or answer_question)(question, script)
    except Exception as e:
        log.warning("press.answer_failed", error=type(e).__name__)
        await send({"type": "answer_status", "question_id": qid, "state": "failed"})
        return
    path, url = answer_file(question.id)
    report: SpeakReport | None = None
    try:
        report = await (voicer or voice_answer)(result.cleared, path)
    except (AnchorConfigError, AnchorError) as e:
        log.warning("press.answer_not_voiced", error=type(e).__name__)
    except Exception:
        log.exception("press.answer_voice_crashed")
    timings = {t.line_id: t for t in report.lines} if report else {}
    lines = []
    for ln in result.cleared.lines:
        t = timings.get(ln.id)
        lines.append(
            {
                "line_id": str(ln.id),
                "text": ln.text,
                "start_ms": t.start_ms if t else None,
                "end_ms": t.end_ms if t else None,
                "words": [list(w) for w in t.words] if t else [],
            }
        )
    voiced = report is not None and bool(report.lines)
    await send(
        {
            "type": "answer_status",
            "question_id": qid,
            "state": "unsure" if result.fallback else "answering",
            "lines": lines,
            "audio_url": url if voiced else None,
            "duration_ms": report.audio_ms if report and voiced else None,
            "total_ms": result.total_ms,
        }
    )
