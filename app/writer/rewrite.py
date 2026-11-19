"""``rewrite_line()``: redraft one line the Editor sent back, from its story's sources.

The Writer gets the line, the Editor's verdict and reason for each failed claim, and the story's
non-retracted sources (same escaped ``<source>`` blocks as drafting). The answer must be exactly
one line and pass ``validate_segment()``; it is resampled once otherwise. The line keeps its id
and order; its text is replaced and its old claims are deleted and replaced by new ``pending``
claims with ``rewrite_round`` set (decision 0013). Rejection history lives in the trace log.
"""

from collections.abc import Sequence
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import delete, select, update

from app.archive import span
from app.config import get_settings
from app.db.models import Claim, ClaimSource, ScriptLine, Source, Story, StorySource, Verdict
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

_sources = Source.__table__  # type: ignore[attr-defined]
_story_sources = StorySource.__table__  # type: ignore[attr-defined]
_lines = ScriptLine.__table__  # type: ignore[attr-defined]
_claims = Claim.__table__  # type: ignore[attr-defined]
_stories = Story.__table__  # type: ignore[attr-defined]


class ClaimFeedback(BaseModel):
    """What the Editor said about one claim. Writer-owned so the Writer never imports the Editor."""

    text: str
    verdict: str
    reason: str


async def load_story_sources(story_id: UUID) -> tuple[str, list[SourceText]]:
    """The story title and its non-retracted sources, oldest first."""
    query = (
        select(
            _sources.c.id,
            _sources.c.outlet,
            _sources.c.title,
            _sources.c.content,
            _sources.c.published_at,
        )
        .join(_story_sources, _story_sources.c.source_id == _sources.c.id)
        .where(_story_sources.c.story_id == story_id, _sources.c.retracted.is_(False))
        .order_by(_sources.c.published_at.asc().nulls_last(), _sources.c.id)
    )
    async with get_engine().connect() as conn:
        title = (
            await conn.execute(select(_stories.c.title).where(_stories.c.id == story_id))
        ).scalar_one_or_none()
        rows = (await conn.execute(query)).all()
    srcs = [SourceText(r.id, r.outlet, r.title, r.content, r.published_at) for r in rows]
    return title or "", srcs


def feedback_block(feedback: Sequence[ClaimFeedback]) -> str:
    return "\n".join(
        f"- [{f.verdict}] {escape_text(f.text)}: {escape_text(f.reason)}" for f in feedback
    )


def rewrite_messages(
    line: DraftLine,
    feedback: Sequence[ClaimFeedback],
    title: str,
    sources: Sequence[SourceText],
    max_chars: int,
) -> tuple[list[llm.Message], dict[str, UUID]]:
    block, refs = sources_block(sources, max_chars)
    user = render(
        "writer/rewrite_user",
        story_title=escape_text(title),
        target_words=max(8, len(line.text.split())),
        line=escape_text(line.text),
        feedback=feedback_block(feedback),
        sources=block,
    )
    return [
        {"role": "system", "content": load_prompt("writer/draft_system")},
        {"role": "user", "content": user},
    ], refs


def _check(seg: DraftSegment, refs: dict[str, UUID]) -> tuple[list[CleanLine], list[str]]:
    lines, problems = validate_segment(seg, refs)
    if len(seg.lines) != 1:
        problems.append(f"return exactly one line, not {len(seg.lines)}")
    return lines, problems


async def rewrite_line(
    line: DraftLine, feedback: Sequence[ClaimFeedback], round_no: int
) -> DraftLine:
    """Rewrite one line and store it. ``WriterError`` if still invalid after one resample."""
    settings = get_settings()
    with span(
        "writer", "rewrite_line", line_id=line.id, round=round_no, feedback=len(feedback)
    ) as s:
        title, sources = await load_story_sources(line.story_id)
        if not sources:
            raise WriterError(f"line {line.id}: story has no usable sources")
        messages, refs = rewrite_messages(
            line, feedback, title, sources, settings.writer_source_max_chars
        )
        seg = await llm.complete("draft", messages, DraftSegment)
        lines, problems = _check(seg, refs)
        attempts = 1
        if problems:
            messages = [
                *messages,
                {"role": "assistant", "content": seg.model_dump_json()},
                {
                    "role": "user",
                    "content": "Your answer broke these rules:\n- "
                    + "\n- ".join(problems)
                    + "\nReturn the corrected JSON.",
                },
            ]
            seg = await llm.complete("draft", messages, DraftSegment)
            lines, problems = _check(seg, refs)
            attempts = 2
        s.set(attempts=attempts, problems=problems)
        if problems:
            raise WriterError(f"line {line.id}: " + "; ".join(problems))
        new = await _store_rewrite(line, lines[0], round_no)
        s.set(claims=len(new.claims), words=len(new.text.split()))
    return new


async def _store_rewrite(line: DraftLine, clean: CleanLine, round_no: int) -> DraftLine:
    claims = [
        Claim(script_line_id=line.id, text=c.text, verdict=Verdict.pending, rewrite_round=round_no)
        for c in clean.claims
    ]
    links = [
        ClaimSource(claim_id=row.id, source_id=sid)
        for row, c in zip(claims, clean.claims, strict=True)
        for sid in c.source_ids
    ]
    async with session_scope() as session:
        await session.exec(update(_lines).where(_lines.c.id == line.id).values(text=clean.text))
        await session.exec(delete(_claims).where(_claims.c.script_line_id == line.id))
        for batch in (claims, links):
            session.add_all(batch)
            await session.flush()
    return DraftLine(
        id=line.id,
        story_id=line.story_id,
        order=line.order,
        text=clean.text,
        claims=[
            DraftClaim(id=row.id, text=c.text, source_ids=c.source_ids)
            for row, c in zip(claims, clean.claims, strict=True)
        ],
    )
