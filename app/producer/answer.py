"""Answer a listener's question on air (task 5.3, decision 0020).

``answer_question``: sources -> Writer (``draft_answer``) -> stored answer lines -> Editor (judge
every claim) -> Standards Desk (``clear_for_air``, briefing status untouched) -> ``ClearedScript``.
If nothing clears, or the loop overruns ``producer_answer_timeout_s``, the answer is one fixed,
claimless line, so the Anchor still says something true.

``handle_question``: what the live session does with a screened ``CallerQuestion``.

Import this module directly (``app.producer.answer``): the Writer imports ``app.producer``.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import text

from app.archive import span
from app.caller.types import CallerQuestion
from app.config import Settings, get_settings
from app.db.session import get_engine
from app.editor import ReviewedScript, judge
from app.log import get_logger
from app.shared.llm import LLMError
from app.standards_desk import ClearedScript, NotClearedError, clear_for_air
from app.writer import Script, WriterError
from app.writer.answer import draft_answer, store_answer
from app.writer.draft import CleanLine, SourceText, load_sources

SAFE_LINE = "I can't confirm more on that from our sources yet."
ANSWERED_INTENTS = frozenset({"follow_up", "background"})

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class AnswerResult:
    cleared: ClearedScript
    fallback: bool  # True when the safe line is all we can say
    total_ms: int


async def answer_sources(
    question: CallerQuestion, script: ClearedScript, max_sources: int
) -> tuple[UUID, str, list[SourceText]]:
    """The story to answer about, its title, and its sources (best first). With no story
    (background), the sources of every story in the briefing."""
    briefing_stories = list(dict.fromkeys(ln.story_id for ln in script.lines))
    story_ids = [question.story_id] if question.story_id else briefing_stories
    anchor_story = question.story_id or (briefing_stories[0] if briefing_stories else None)
    if anchor_story is None:
        return UUID(int=0), "", []
    async with get_engine().connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT ss.source_id FROM story_sources ss"
                    " JOIN sources s ON s.id = ss.source_id"
                    " WHERE ss.story_id = ANY(:ids) AND NOT s.retracted"
                    " ORDER BY s.trust_score DESC, s.published_at DESC NULLS LAST LIMIT :n"
                ),
                {"ids": story_ids, "n": max_sources},
            )
        ).all()
        title = (
            await conn.execute(text("SELECT title FROM stories WHERE id = :i"), {"i": anchor_story})
        ).scalar_one_or_none()
    texts = await load_sources([r.source_id for r in rows])
    ordered = [texts[r.source_id] for r in rows if r.source_id in texts]
    return anchor_story, (title or "") if question.story_id else "", ordered


async def _safe_answer(
    question: CallerQuestion, script: ClearedScript, story_id: UUID
) -> ClearedScript:
    lines = await store_answer(
        script.briefing_id, story_id, question.transcript, [CleanLine(SAFE_LINE, [])]
    )
    reviewed = ReviewedScript(
        script=Script(briefing_id=script.briefing_id, lines=lines), verdicts=[], rounds=0
    )
    return await clear_for_air(reviewed, mark_briefing=False)


async def answer_question(
    question: CallerQuestion, script: ClearedScript, *, settings: Settings | None = None
) -> AnswerResult:
    settings = settings or get_settings()
    t0 = time.perf_counter()
    marks: dict[str, int] = {}

    def mark(name: str) -> None:
        marks[name] = round((time.perf_counter() - t0) * 1000)

    with span(
        "producer",
        "answer",
        script.briefing_id,
        question_id=question.id,
        intent=question.intent,
        budget_s=settings.producer_answer_budget_s,
    ) as s:
        story_id = question.story_id or (script.lines[0].story_id if script.lines else UUID(int=0))
        cleared: ClearedScript | None = None
        reason = ""
        try:
            async with asyncio.timeout(settings.producer_answer_timeout_s):
                story_id, title, sources = await answer_sources(
                    question, script, settings.producer_answer_max_sources
                )
                mark("sources_ms")
                if sources:
                    asked = question.restated or question.transcript
                    drafted = await draft_answer(
                        asked,
                        title,
                        sources,
                        max_lines=settings.producer_answer_max_lines,
                        max_chars=settings.producer_answer_source_max_chars,
                    )
                    mark("draft_ms")
                    lines = await store_answer(
                        script.briefing_id, story_id, question.transcript, drafted
                    )
                    claims = [c for ln in lines for c in ln.claims]
                    verdicts = await judge.judge_all(
                        claims, {c.id: ln.id for ln in lines for c in ln.claims}
                    )
                    await judge.store_verdicts(verdicts)  # no briefing id: status untouched
                    mark("judge_ms")
                    s.set(
                        claims=len(claims),
                        approved=sum(v.verdict == "approved" for v in verdicts),
                    )
                    reviewed = ReviewedScript(
                        script=Script(briefing_id=script.briefing_id, lines=lines),
                        verdicts=verdicts,
                        rounds=0,
                    )
                    cleared = await clear_for_air(reviewed, mark_briefing=False)
                    mark("clear_ms")
                else:
                    reason = "no sources"
        except TimeoutError:
            reason = "timeout"
        except NotClearedError:
            reason = "nothing cleared"
        except (WriterError, LLMError) as e:
            reason = type(e).__name__
        fallback = cleared is None
        if cleared is None:
            cleared = await _safe_answer(question, script, story_id)
        total = round((time.perf_counter() - t0) * 1000)
        s.set(
            **marks,
            total_ms=total,
            fallback=fallback,
            fallback_reason=reason,
            cleared=len(cleared.lines),
            over_budget=total > settings.producer_answer_budget_s * 1000,
        )
        if fallback:
            log.info("producer.answer_fallback", reason=reason)
    return AnswerResult(cleared, fallback, total)


class Session(Protocol):
    async def send_event(self, event: dict[str, Any]) -> None: ...
    async def resume(self) -> None: ...
    def interject(self, script: Any, question_id: str) -> None: ...


Answerer = Callable[[CallerQuestion, ClearedScript], Awaitable[AnswerResult]]


async def handle_question(
    question: CallerQuestion,
    script: ClearedScript,
    session: Session,
    *,
    answerer: Answerer | None = None,
) -> None:
    """Answer an allowed follow-up or background question, then resume the briefing. Anything
    else (blocked, off topic, unknown) resumes at once without an answer."""
    qid = str(question.id)
    allowed = question.screen is None or question.screen.allowed
    if not allowed or question.intent not in ANSWERED_INTENTS:
        await session.send_event({"type": "answer_status", "question_id": qid, "state": "declined"})
        await session.resume()
        return
    await session.send_event({"type": "answer_status", "question_id": qid, "state": "thinking"})
    try:
        result = await (answerer or answer_question)(question, script)
    except Exception as e:  # never leave the listener paused forever
        log.warning("producer.answer_failed", error=type(e).__name__)
        await session.send_event({"type": "answer_status", "question_id": qid, "state": "failed"})
        await session.resume()
        return
    await session.send_event(
        {
            "type": "answer_status",
            "question_id": qid,
            "state": "unsure" if result.fallback else "answering",
            "lines": [{"line_id": str(ln.id), "text": ln.text} for ln in result.cleared.lines],
            "total_ms": result.total_ms,
        }
    )
    session.interject(result.cleared, qid)
    await session.resume()
