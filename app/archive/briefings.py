"""Briefing timeline for the Archive dashboard: briefings, their script lines, and per-stage
latency and cost rebuilt from ``traces`` (task 3.3)."""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.archive.corrections import CorrectionRef, corrections_for
from app.archive.span import span
from app.db.session import get_engine

LLM_COMPONENT = "llm-gateway"


class BriefingNotFoundError(LookupError):
    """No briefing with that id."""


class BriefingSummary(BaseModel):
    id: UUID
    created_at: datetime
    status: str
    target_minutes: float
    lines: int
    verdicts: dict[str, int]  # claim count per verdict
    cost_usd: float
    tokens_in: int
    tokens_out: int
    wall_ms: float | None  # first span start to last span end
    corrections: int = 0  # claims affected by a retracted source (task 6.2)


class LineSummary(BaseModel):
    id: UUID
    order: int
    text: str
    story_title: str | None
    verdicts: dict[str, int]
    kind: str = "script"  # "answer": reply to a listener (task 5.3); "correction" (task 6.2)
    question: str | None = None  # what an answer line replies to


class Stage(BaseModel):
    """One component's share of a briefing. ``latency_ms`` sums the component's entry spans
    (its own top-level steps); LLM calls made inside it are counted in ``llm_*``."""

    component: str
    steps: int
    latency_ms: float
    llm_calls: int
    llm_ms: float  # summed, so parallel calls can exceed latency_ms
    cost_usd: float
    tokens_in: int
    tokens_out: int
    errors: int


class BriefingDetail(BaseModel):
    briefing: BriefingSummary
    lines: list[LineSummary]
    stages: list[Stage]
    corrections: list[CorrectionRef] = []  # claims of this briefing hit by a retraction


# ---- pure: stages from spans ----------------------------------------------------------------


def stages_from_spans(rows: Iterable[Mapping[Any, Any]]) -> list[Stage]:
    """Group a briefing's spans by component. A span is an entry span when its parent is missing
    or in another component. LLM-gateway spans are charged to the nearest non-gateway ancestor."""
    spans = {r["id"]: r for r in rows}

    def owner(r: Mapping[Any, Any]) -> str:
        seen: set[Any] = set()
        while r["component"] == LLM_COMPONENT:
            parent = spans.get(r["parent_id"])
            if parent is None or parent["id"] in seen:
                return LLM_COMPONENT
            seen.add(parent["id"])
            r = parent
        return str(r["component"])

    acc: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    order: list[str] = []
    for r in sorted(spans.values(), key=lambda r: r["started_at"]):
        comp = owner(r)
        if comp not in acc:
            order.append(comp)
        a = acc[comp]
        a["cost_usd"] += r["cost_usd"] or 0.0
        a["tokens_in"] += r["tokens_in"] or 0
        a["tokens_out"] += r["tokens_out"] or 0
        a["errors"] += 1 if r["error"] else 0
        if r["component"] == LLM_COMPONENT:
            a["llm_calls"] += 1
            a["llm_ms"] += r["latency_ms"] or 0.0
            if comp != LLM_COMPONENT:
                continue
        parent = spans.get(r["parent_id"])
        if parent is None or parent["component"] != r["component"]:
            a["steps"] += 1
            a["latency_ms"] += r["latency_ms"] or 0.0
    return [
        Stage(
            component=c,
            steps=int(acc[c]["steps"]),
            latency_ms=acc[c]["latency_ms"],
            llm_calls=int(acc[c]["llm_calls"]),
            llm_ms=acc[c]["llm_ms"],
            cost_usd=acc[c]["cost_usd"],
            tokens_in=int(acc[c]["tokens_in"]),
            tokens_out=int(acc[c]["tokens_out"]),
            errors=int(acc[c]["errors"]),
        )
        for c in order
    ]


# ---- queries --------------------------------------------------------------------------------

_SUMMARY_SQL = """
SELECT b.id, b.created_at, b.status, b.target_minutes,
  (SELECT count(*) FROM script_lines l WHERE l.briefing_id = b.id) AS lines,
  (SELECT count(*) FROM corrections c WHERE c.briefing_id = b.id) AS corrections,
  coalesce(t.cost_usd, 0) AS cost_usd, coalesce(t.tokens_in, 0) AS tokens_in,
  coalesce(t.tokens_out, 0) AS tokens_out, t.wall_ms
FROM briefings b
LEFT JOIN LATERAL (
  SELECT sum(cost_usd) AS cost_usd, sum(tokens_in) AS tokens_in, sum(tokens_out) AS tokens_out,
    extract(epoch FROM max(started_at + coalesce(latency_ms, 0) * interval '1 millisecond')
      - min(started_at)) * 1000 AS wall_ms
  FROM traces WHERE briefing_id = b.id
) t ON true
"""


async def _verdicts(conn: AsyncConnection, briefing_ids: list[UUID]) -> dict[UUID, dict[str, int]]:
    out: dict[UUID, dict[str, int]] = {b: {} for b in briefing_ids}
    if not briefing_ids:
        return out
    rows = await conn.execute(
        text(
            "SELECT l.briefing_id, c.verdict, count(*) AS n FROM claims c"
            " JOIN script_lines l ON l.id = c.script_line_id"
            " WHERE l.briefing_id = ANY(:ids) GROUP BY l.briefing_id, c.verdict"
        ),
        {"ids": briefing_ids},
    )
    for r in rows:
        out[r.briefing_id][r.verdict] = r.n
    return out


def _summary(r: Any, verdicts: dict[str, int]) -> BriefingSummary:
    return BriefingSummary(
        id=r.id,
        created_at=r.created_at,
        status=r.status,
        target_minutes=r.target_minutes,
        lines=r.lines,
        verdicts=verdicts,
        cost_usd=float(r.cost_usd),
        tokens_in=int(r.tokens_in),
        tokens_out=int(r.tokens_out),
        wall_ms=float(r.wall_ms) if r.wall_ms is not None else None,
        corrections=int(r.corrections),
    )


async def list_briefings(limit: int = 50) -> list[BriefingSummary]:
    """Newest first."""
    with span("archive", "list_briefings", limit=limit) as s:
        async with get_engine().connect() as conn:
            rows = (
                await conn.execute(
                    text(_SUMMARY_SQL + " ORDER BY b.created_at DESC LIMIT :n"), {"n": limit}
                )
            ).all()
            verdicts = await _verdicts(conn, [r.id for r in rows])
        s.set(rows=len(rows))
    return [_summary(r, verdicts[r.id]) for r in rows]


async def briefing_detail(briefing_id: UUID) -> BriefingDetail:
    # Read spans keep the id in the payload, not ``briefing_id``: viewing a briefing must not
    # add to its own timeline.
    with span("archive", "briefing_detail", briefing=briefing_id) as s:
        async with get_engine().connect() as conn:
            row = (
                await conn.execute(text(_SUMMARY_SQL + " WHERE b.id = :b"), {"b": briefing_id})
            ).one_or_none()
            if row is None:
                raise BriefingNotFoundError(f"no briefing {briefing_id}")
            verdicts = await _verdicts(conn, [briefing_id])
            lines = (
                await conn.execute(
                    text(
                        'SELECT l.id, l."order", l.text, l.kind, l.question,'
                        " st.title AS story_title"
                        " FROM script_lines l LEFT JOIN stories st ON st.id = l.story_id"
                        ' WHERE l.briefing_id = :b ORDER BY l."order"'
                    ),
                    {"b": briefing_id},
                )
            ).all()
            line_verdicts: dict[UUID, dict[str, int]] = {ln.id: {} for ln in lines}
            for r in await conn.execute(
                text(
                    "SELECT c.script_line_id, c.verdict, count(*) AS n FROM claims c"
                    " JOIN script_lines l ON l.id = c.script_line_id WHERE l.briefing_id = :b"
                    " GROUP BY c.script_line_id, c.verdict"
                ),
                {"b": briefing_id},
            ):
                line_verdicts[r.script_line_id][r.verdict] = r.n
            spans = (
                (
                    await conn.execute(
                        text(
                            "SELECT id, parent_id, component, started_at, latency_ms, cost_usd,"
                            " tokens_in, tokens_out, error FROM traces WHERE briefing_id = :b"
                        ),
                        {"b": briefing_id},
                    )
                )
                .mappings()
                .all()
            )
            corrections = await corrections_for(conn, briefing_id, 200)
        s.set(lines=len(lines), spans=len(spans))
    return BriefingDetail(
        briefing=_summary(row, verdicts[briefing_id]),
        lines=[
            LineSummary(
                id=ln.id,
                order=ln.order,
                text=ln.text,
                story_title=ln.story_title,
                verdicts=line_verdicts[ln.id],
                kind=ln.kind,
                question=ln.question,
            )
            for ln in lines
        ],
        stages=stages_from_spans(spans),
        corrections=corrections,
    )
