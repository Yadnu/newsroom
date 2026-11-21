"""Corrections (task 6.2, decision 0023): what a source retraction does to the briefings that
used it.

- ``flag_retraction`` records a ``corrections`` row per affected claim, inside the retraction's
  transaction: ``orphaned`` when no evidence from a live source is left, ``weakened`` otherwise.
  ``on_air`` when the briefing aired with that claim approved.
- Unaired briefings need nothing more: ``clear_for_air`` already blocks a line whose evidence is all
  retracted when the Anchor clears it again.
- ``queue_corrections`` puts one fixed-template correction line per pending ``on_air`` claim at the
  top of a new briefing (negative orders). The template repeats only our own approved claim and the
  outlet, so a correction can never add an unverified fact; ``clear_for_air`` checks the line
  against its ``corrections`` row word for word.
"""

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.archive import span
from app.config import get_settings
from app.db.models import BriefingStatus, Verdict, utcnow
from app.db.session import get_engine
from app.log import get_logger
from app.writer import DraftLine

log = get_logger(__name__)

_LOWER_FIRST = frozenset({"the", "a", "an", "it", "its", "this", "that", "these", "those", "there"})


def correction_text(claim_text: str, outlet: str) -> str:
    """The on-air correction for one claim. Deterministic: ``clear_for_air`` re-renders it."""
    claim = claim_text.strip().rstrip(".!?;: ")
    first, _, rest = claim.partition(" ")
    if first.lower() in _LOWER_FIRST:
        claim = f"{first.lower()} {rest}".strip()
    return (
        f"A correction: in an earlier briefing we reported that {claim}. That relied on a report "
        f"from {outlet.strip()} that has since been withdrawn, so we can no longer stand by it."
    )


@dataclass(frozen=True, slots=True)
class Flagged:
    """One affected briefing."""

    briefing_id: UUID
    status: str
    orphaned: int
    weakened: int
    on_air: int


async def flag_retraction(conn: AsyncConnection, source_id: UUID) -> list[Flagged]:
    """Record the claims that cited, or were judged on, a source that was just retracted.
    Runs on the caller's connection after ``sources.retracted`` is set, so the retracted source no
    longer counts as live evidence. Re-running adds nothing (unique source + claim)."""
    rows = (
        await conn.execute(
            text(
                "SELECT c.id AS claim_id, c.text, c.verdict, l.id AS line_id, l.briefing_id,"
                " b.status,"
                " (SELECT count(*) FROM claim_evidence e JOIN sources s ON s.id = e.source_id"
                "   WHERE e.claim_id = c.id AND NOT s.retracted) AS live"
                " FROM claims c JOIN script_lines l ON l.id = c.script_line_id"
                " JOIN briefings b ON b.id = l.briefing_id"
                " WHERE c.id IN (SELECT claim_id FROM claim_sources WHERE source_id = :s"
                "                UNION SELECT claim_id FROM claim_evidence WHERE source_id = :s)"
                ' ORDER BY b.created_at, l."order"'
            ),
            {"s": source_id},
        )
    ).all()
    by_briefing: dict[UUID, list[tuple[str, bool]]] = {}
    status_of: dict[UUID, str] = {}
    for r in rows:
        impact = "orphaned" if r.live == 0 else "weakened"
        on_air = (
            r.status == BriefingStatus.aired.value
            and r.verdict == Verdict.approved.value
            and impact == "orphaned"
        )
        inserted = (
            await conn.execute(
                text(
                    "INSERT INTO corrections (id, source_id, briefing_id, script_line_id, claim_id,"
                    " claim_text, impact, on_air, created_at)"
                    " VALUES (:id, :s, :b, :l, :c, :t, :i, :a, :at)"
                    " ON CONFLICT (source_id, claim_id) DO NOTHING RETURNING id"
                ),
                {
                    "id": uuid4(),
                    "s": source_id,
                    "b": r.briefing_id,
                    "l": r.line_id,
                    "c": r.claim_id,
                    "t": r.text,
                    "i": impact,
                    "a": on_air,
                    "at": utcnow(),
                },
            )
        ).first()
        if inserted is not None:
            by_briefing.setdefault(r.briefing_id, []).append((impact, on_air))
            status_of[r.briefing_id] = r.status
    flagged = []
    for bid, hits in by_briefing.items():
        f = Flagged(
            bid,
            status_of[bid],
            sum(i == "orphaned" for i, _ in hits),
            sum(i == "weakened" for i, _ in hits),
            sum(a for _, a in hits),
        )
        with span(
            "standards-desk",
            "flag_briefing",
            bid,
            source_id=source_id,
            status=f.status,
            orphaned=f.orphaned,
            weakened=f.weakened,
            on_air=f.on_air,
        ):
            pass
        flagged.append(f)
    return flagged


async def queue_corrections(briefing_id: UUID, max_lines: int | None = None) -> list[DraftLine]:
    """Put pending on-air corrections at the top of ``briefing_id``. Returns the new lines."""
    limit = get_settings().standards_max_corrections if max_lines is None else max_lines
    with span("standards-desk", "queue_corrections", briefing_id, limit=limit) as s:
        async with get_engine().begin() as conn:
            pending = (
                await conn.execute(
                    text(
                        "SELECT DISTINCT ON (c.claim_id) c.claim_id, c.claim_text, s.outlet,"
                        " l.story_id, c.created_at"
                        " FROM corrections c JOIN sources s ON s.id = c.source_id"
                        " JOIN script_lines l ON l.id = c.script_line_id"
                        " WHERE c.on_air AND c.correction_line_id IS NULL AND s.retracted"
                        "   AND c.briefing_id <> :b AND l.story_id IS NOT NULL"
                        " ORDER BY c.claim_id, c.created_at"
                    ),
                    {"b": briefing_id},
                )
            ).all()
            pending = sorted(pending, key=lambda r: r.created_at)[:limit]
            queued: list[DraftLine] = []
            for n, r in enumerate(pending):
                line_id = uuid4()
                body = correction_text(r.claim_text, r.outlet)
                await conn.execute(
                    text(
                        'INSERT INTO script_lines (id, briefing_id, story_id, "order", text, kind)'
                        " VALUES (:id, :b, :story, :o, :t, 'correction')"
                    ),
                    {
                        "id": line_id,
                        "b": briefing_id,
                        "story": r.story_id,
                        "o": n - len(pending),
                        "t": body,
                    },
                )
                await conn.execute(
                    text(
                        "UPDATE corrections SET correction_line_id = :l"
                        " WHERE claim_id = :c AND on_air AND correction_line_id IS NULL"
                    ),
                    {"l": line_id, "c": r.claim_id},
                )
                queued.append(
                    DraftLine(
                        id=line_id,
                        story_id=r.story_id,
                        order=n - len(pending),
                        text=body,
                        claims=[],
                        kind="correction",
                    )
                )
        s.set(queued=len(queued))
    if queued:
        log.info("standards.corrections_queued", briefing=str(briefing_id), lines=len(queued))
    return queued
