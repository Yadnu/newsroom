"""``draft_answer()``: the anchor's short spoken answer to a listener question (task 5.3).

Same output schema and validation as story segments (claims cite ``S<n>`` sources, short quotes).
The question and the sources are untrusted data: escaped, in the user turn only.
"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select

from app.archive import span
from app.db.models import Claim, ClaimSource, ScriptLine, Verdict
from app.db.session import get_engine, session_scope
from app.shared import llm
from app.writer.draft import (
    CleanLine,
    DraftClaim,
    DraftLine,
    DraftSegment,
    SourceText,
    WriterError,
    sources_block,
    validate_segment,
)
from app.writer.prompts import escape_text, load_prompt, render

ANSWER_ORDER_BASE = 1000  # answer lines sit after the script in the briefing's line order
WORDS_PER_LINE = 22

_lines = ScriptLine.__table__  # type: ignore[attr-defined]


def answer_messages(
    question: str,
    story_title: str,
    sources: Sequence[SourceText],
    max_lines: int,
    max_chars: int,
) -> tuple[list[llm.Message], dict[str, UUID]]:
    block, refs = sources_block(sources, max_chars)
    user = render(
        "writer/answer_user",
        question=escape_text(question.strip()),
        story_title=escape_text(story_title) or "(several stories)",
        max_lines=max_lines,
        max_words=max_lines * WORDS_PER_LINE,
        sources=block,
    )
    return [
        {"role": "system", "content": load_prompt("writer/answer_system")},
        {"role": "user", "content": user},
    ], refs


async def draft_answer(
    question: str,
    story_title: str,
    sources: Sequence[SourceText],
    *,
    max_lines: int = 3,
    max_chars: int = 4000,
) -> list[CleanLine]:
    """At most ``max_lines`` lines. One retry with the rule violations, then ``WriterError``."""
    messages, refs = answer_messages(question, story_title, sources, max_lines, max_chars)
    with span("writer", "draft_answer", sources=len(sources), max_lines=max_lines) as s:
        seg = await llm.complete("answer", messages, DraftSegment)
        lines, problems = validate_segment(seg, refs)
        attempts = 1
        if problems:
            messages = [
                *messages,
                {"role": "assistant", "content": seg.model_dump_json()},
                {
                    "role": "user",
                    "content": "Your answer broke these rules:\n- "
                    + "\n- ".join(problems)
                    + "\nReturn the corrected JSON for the whole answer.",
                },
            ]
            seg = await llm.complete("answer", messages, DraftSegment)
            lines, problems = validate_segment(seg, refs)
            attempts = 2
        lines = lines[:max_lines]
        s.set(
            attempts=attempts,
            lines=len(lines),
            claims=sum(len(ln.claims) for ln in lines),
            words=sum(len(ln.text.split()) for ln in lines),
            problems=problems,
        )
        if problems:
            raise WriterError("answer: " + "; ".join(problems))
    return lines


async def next_answer_order(briefing_id: UUID) -> int:
    async with get_engine().connect() as conn:
        top = (
            await conn.execute(
                select(func.max(_lines.c.order)).where(_lines.c.briefing_id == briefing_id)
            )
        ).scalar_one_or_none()
    return max(ANSWER_ORDER_BASE, (top or 0) + 1)


async def store_answer(
    briefing_id: UUID, story_id: UUID, question: str, lines: Sequence[CleanLine]
) -> list[DraftLine]:
    """Store answer lines (``kind='answer'``) with pending claims and their cited sources."""
    order = await next_answer_order(briefing_id)
    out: list[DraftLine] = []
    rows_lines: list[ScriptLine] = []
    rows_claims: list[Claim] = []
    rows_links: list[ClaimSource] = []
    for i, line in enumerate(lines):
        row = ScriptLine(
            briefing_id=briefing_id,
            story_id=story_id,
            order=order + i,
            text=line.text,
            kind="answer",
            question=question,
        )
        rows_lines.append(row)
        claims = []
        for c in line.claims:
            claim = Claim(script_line_id=row.id, text=c.text, verdict=Verdict.pending)
            rows_claims.append(claim)
            rows_links.extend(ClaimSource(claim_id=claim.id, source_id=sid) for sid in c.source_ids)
            claims.append(DraftClaim(id=claim.id, text=c.text, source_ids=c.source_ids))
        out.append(
            DraftLine(id=row.id, story_id=story_id, order=order + i, text=line.text, claims=claims)
        )
    async with session_scope() as session:
        for batch in (rows_lines, rows_claims, rows_links):
            session.add_all(batch)
            await session.flush()
    return out
