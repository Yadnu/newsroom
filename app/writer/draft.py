"""``draft_script()``: turn a rundown into spoken lines with claims tagged to sources.

One LLM call per rundown item (task "draft"), run concurrently. Sources go in delimited, escaped
``<source id="S<n>">`` blocks in the user turn; the system prompt is static. Output is validated
(every factual line has a claim, every claim cites a known source, quotes under 15 words) and
resampled once with the violations if it fails. Lines, claims (``pending``) and the cited sources
(``claim_sources``) are stored in one transaction.
"""

import asyncio
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select

from app.archive import span
from app.config import get_settings
from app.db.models import Claim, ClaimSource, ScriptLine, Source, Verdict
from app.db.session import get_engine, session_scope
from app.log import get_logger
from app.producer import Rundown, RundownItem
from app.shared import llm
from app.writer.prompts import escape_attr, escape_text, load_prompt, render

MAX_QUOTE_WORDS = 14  # quotes must be under 15 words
_QUOTE = re.compile(r"\"([^\"]+)\"|“([^”]+)”")
_REF = re.compile(r"^S(\d+)$")

log = get_logger(__name__)
_sources = Source.__table__  # type: ignore[attr-defined]


class WriterError(Exception):
    """The model could not produce a valid segment after a resample."""


# ---- LLM output schema ----------------------------------------------------------------------


class DraftClaimOut(BaseModel):
    text: str
    sources: list[str]


class DraftLineOut(BaseModel):
    text: str
    factual: bool
    claims: list[DraftClaimOut]


class DraftSegment(BaseModel):
    lines: list[DraftLineOut]


# ---- public result --------------------------------------------------------------------------


class DraftClaim(BaseModel):
    id: UUID
    text: str
    source_ids: list[UUID]


class DraftLine(BaseModel):
    id: UUID
    story_id: UUID
    order: int
    text: str
    claims: list[DraftClaim]


class Script(BaseModel):
    briefing_id: UUID
    lines: list[DraftLine]


# ---- validation (pure) ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CleanClaim:
    text: str
    source_ids: list[UUID]


@dataclass(frozen=True, slots=True)
class CleanLine:
    text: str
    claims: list[CleanClaim]


def quote_violations(text: str) -> list[str]:
    out = []
    for m in _QUOTE.finditer(text):
        quoted = (m.group(1) or m.group(2) or "").strip()
        if len(quoted.split()) > MAX_QUOTE_WORDS:
            out.append(
                f'quote of {len(quoted.split())} words (limit {MAX_QUOTE_WORDS}): "{quoted[:60]}"'
            )
    return out


def validate_segment(seg: DraftSegment, refs: dict[str, UUID]) -> tuple[list[CleanLine], list[str]]:
    """Map S<n> refs to source ids, drop unknown refs, and list rule violations."""
    lines: list[CleanLine] = []
    problems: list[str] = []
    if not seg.lines:
        problems.append("the segment has no lines")
    for n, line in enumerate(seg.lines, 1):
        text = line.text.strip()
        if not text:
            problems.append(f"line {n} is empty")
            continue
        claims = []
        for c in line.claims:
            ids = list(dict.fromkeys(refs[r] for r in (s.strip() for s in c.sources) if r in refs))
            if c.text.strip() and ids:
                claims.append(CleanClaim(c.text.strip(), ids))
            else:
                problems.append(f"line {n}: claim {c.text[:50]!r} cites no known source")
        if line.factual and not claims:
            problems.append(f"line {n} is factual but has no claim with a known source")
        problems.extend(f"line {n}: {q}" for q in quote_violations(text))
        lines.append(CleanLine(text, claims))
    return lines, problems


# ---- prompting --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceText:
    id: UUID
    outlet: str
    title: str
    content: str
    published_at: datetime | None


def sources_block(sources: Sequence[SourceText], max_chars: int) -> tuple[str, dict[str, UUID]]:
    refs: dict[str, UUID] = {}
    blocks = []
    for i, s in enumerate(sources, 1):
        ref = f"S{i}"
        refs[ref] = s.id
        published = s.published_at.isoformat() if s.published_at else "unknown"
        body = escape_text(f"{s.title}\n{s.content}"[:max_chars])
        blocks.append(
            f'<source id="{ref}" outlet="{escape_attr(s.outlet)}" published="{published}">\n'
            f"{body}\n</source>"
        )
    return "\n\n".join(blocks), refs


def segment_messages(
    item: RundownItem, sources: Sequence[SourceText], target_words: int, max_chars: int
) -> tuple[list[llm.Message], dict[str, UUID]]:
    block, refs = sources_block(sources, max_chars)
    user = render(
        "writer/draft_user",
        story_title=escape_text(item.title),
        target_words=target_words,
        sources=block,
    )
    return [
        {"role": "system", "content": load_prompt("writer/draft_system")},
        {"role": "user", "content": user},
    ], refs


async def draft_segment(item: RundownItem, sources: Sequence[SourceText]) -> list[CleanLine]:
    settings = get_settings()
    target_words = max(10, round(item.target_seconds * settings.writer_words_per_second))
    messages, refs = segment_messages(item, sources, target_words, settings.writer_source_max_chars)
    with span("writer", "draft_segment", story_id=item.story_id, target_words=target_words) as s:
        seg = await llm.complete("draft", messages, DraftSegment)
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
                    + "\nReturn the corrected JSON for the whole segment.",
                },
            ]
            seg = await llm.complete("draft", messages, DraftSegment)
            lines, problems = validate_segment(seg, refs)
            attempts = 2
        s.set(
            attempts=attempts,
            lines=len(lines),
            claims=sum(len(line.claims) for line in lines),
            words=sum(len(line.text.split()) for line in lines),
            problems=problems,
        )
        if problems:
            raise WriterError(f"story {item.story_id}: " + "; ".join(problems))
    return lines


# ---- draft_script -----------------------------------------------------------------------------


async def load_sources(ids: Sequence[UUID]) -> dict[UUID, SourceText]:
    if not ids:
        return {}
    query = select(
        _sources.c.id,
        _sources.c.outlet,
        _sources.c.title,
        _sources.c.content,
        _sources.c.published_at,
    ).where(_sources.c.id.in_(list(ids)), _sources.c.retracted.is_(False))
    async with get_engine().connect() as conn:
        rows = (await conn.execute(query)).all()
    return {r.id: SourceText(r.id, r.outlet, r.title, r.content, r.published_at) for r in rows}


async def draft_script(rundown: Rundown) -> Script:
    with span("writer", "draft_script", rundown.briefing_id, stories=len(rundown.items)) as s:
        texts = await load_sources([ref.id for item in rundown.items for ref in item.sources])
        work: list[tuple[RundownItem, list[SourceText]]] = []
        for item in sorted(rundown.items, key=lambda i: i.order):
            usable = [texts[ref.id] for ref in item.sources if ref.id in texts]
            if usable:
                work.append((item, usable))
            else:
                log.warning(
                    "writer.story_skipped", story_id=str(item.story_id), reason="no sources"
                )
        if not work:
            raise WriterError("no rundown item has usable sources")

        segments = await asyncio.gather(*(draft_segment(item, srcs) for item, srcs in work))
        script = await _store(rundown.briefing_id, [item for item, _ in work], segments)
        s.set(
            lines=len(script.lines),
            claims=sum(len(line.claims) for line in script.lines),
            skipped=len(rundown.items) - len(work),
        )
    return script


async def _store(
    briefing_id: UUID, items: Sequence[RundownItem], segments: Sequence[list[CleanLine]]
) -> Script:
    out: list[DraftLine] = []
    rows_lines: list[ScriptLine] = []
    rows_claims: list[Claim] = []
    rows_links: list[ClaimSource] = []
    order = 0
    for item, lines in zip(items, segments, strict=True):
        for line in lines:
            row = ScriptLine(
                briefing_id=briefing_id, story_id=item.story_id, order=order, text=line.text
            )
            rows_lines.append(row)
            claims = []
            for c in line.claims:
                claim = Claim(script_line_id=row.id, text=c.text, verdict=Verdict.pending)
                rows_claims.append(claim)
                rows_links.extend(
                    ClaimSource(claim_id=claim.id, source_id=sid) for sid in c.source_ids
                )
                claims.append(DraftClaim(id=claim.id, text=c.text, source_ids=c.source_ids))
            out.append(
                DraftLine(
                    id=row.id, story_id=item.story_id, order=order, text=line.text, claims=claims
                )
            )
            order += 1
    async with session_scope() as session:
        # Flush per table so FK targets exist first (the models declare no relationships).
        for batch in (rows_lines, rows_claims, rows_links):
            session.add_all(batch)
            await session.flush()
    return Script(briefing_id=briefing_id, lines=out)
