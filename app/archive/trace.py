"""Read side of the Archive: trace a script line to its sources, and list Editor rejections.

Current claims, their citations and evidence come from ``claims`` / ``claim_sources`` /
``claim_evidence``. Claims replaced by a rewrite are deleted (decision 0013), so the judgement
history comes from ``editor/judge_claim`` trace rows, which carry ``claim_id``, ``line_id`` (from
task 3.1 on), ``claim``, ``verdict``, ``reason``, ``checks`` and ``score``.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.archive.span import span
from app.db.session import get_engine

JUDGE_COMPONENT, JUDGE_EVENT = "editor", "judge_claim"
REJECTING = ("rejected",)
REJECTING_OR_REWRITE = ("rejected", "rewrite")


class TraceNotFoundError(LookupError):
    """No script line with that id."""


class SourceRef(BaseModel):
    id: UUID
    outlet: str
    title: str
    url: str
    published_at: datetime | None
    retracted: bool


class EvidenceRef(BaseModel):
    source: SourceRef
    passage: str
    score: float | None


class TracedClaim(BaseModel):
    id: UUID
    text: str
    verdict: str
    score: float | None
    reason: str | None
    rewrite_round: int
    judged_at: datetime | None
    cited: list[SourceRef]
    evidence: list[EvidenceRef]


class Judgement(BaseModel):
    """One ``editor/judge_claim`` span. ``current``: the claim is still in ``claims``."""

    trace_id: UUID
    at: datetime
    claim_id: UUID | None
    claim: str
    verdict: str
    score: float | None
    reason: str
    checks: dict[str, bool]
    current: bool


class ClaimTrace(BaseModel):
    line_id: UUID
    briefing_id: UUID
    story_id: UUID | None
    story_title: str | None
    order: int
    text: str
    audio_start_ms: int | None
    audio_end_ms: int | None
    claims: list[TracedClaim]
    history: list[Judgement]  # every judgement of a claim on this line, oldest first


class Rejection(Judgement):
    briefing_id: UUID | None
    line_id: UUID | None
    line_text: str | None  # None for spans recorded before task 3.1 (no line_id)


# ---- payload parsing (pure) -----------------------------------------------------------------


def _uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except ValueError:
        return None


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def judgement_from_trace(row: Mapping[Any, Any], current_ids: set[UUID]) -> Judgement:
    """A ``Judgement`` from a traces row (id, started_at, payload). Tolerates old payloads."""
    p = row["payload"] if isinstance(row["payload"], Mapping) else {}
    claim_id = _uuid(p.get("claim_id"))
    checks = p.get("checks")
    return Judgement(
        trace_id=row["id"],
        at=row["started_at"],
        claim_id=claim_id,
        claim=str(p.get("claim") or ""),
        verdict=str(p.get("verdict") or "unknown"),
        score=_float(p.get("score")),
        reason=str(p.get("reason") or ""),
        checks={str(k): bool(v) for k, v in checks.items()} if isinstance(checks, Mapping) else {},
        current=claim_id in current_ids,
    )


def line_id_of(row: Mapping[Any, Any]) -> UUID | None:
    p = row["payload"]
    return _uuid(p.get("line_id")) if isinstance(p, Mapping) else None


# ---- queries --------------------------------------------------------------------------------

_SOURCE_COLS = "s.id, s.outlet, s.title, s.url, s.published_at, s.retracted"


def _source(r: Any) -> SourceRef:
    return SourceRef(
        id=r.id,
        outlet=r.outlet,
        title=r.title,
        url=r.url,
        published_at=r.published_at,
        retracted=r.retracted,
    )


async def _existing_claims(conn: AsyncConnection, ids: Sequence[UUID]) -> set[UUID]:
    if not ids:
        return set()
    rows = await conn.execute(
        text("SELECT id FROM claims WHERE id = ANY(:ids)"), {"ids": list(set(ids))}
    )
    return {r.id for r in rows}


async def claim_trace(script_line_id: UUID) -> ClaimTrace:
    """Everything behind one script line: current claims with cited sources and evidence,
    plus every judgement of its claims (including claims replaced by rewrites)."""
    with span("archive", "claim_trace", line_id=script_line_id) as s:
        async with get_engine().connect() as conn:
            line = (
                await conn.execute(
                    text(
                        "SELECT l.id, l.briefing_id, l.story_id, st.title AS story_title,"
                        ' l."order", l.text, l.audio_start_ms, l.audio_end_ms'
                        " FROM script_lines l LEFT JOIN stories st ON st.id = l.story_id"
                        " WHERE l.id = :id"
                    ),
                    {"id": script_line_id},
                )
            ).one_or_none()
            if line is None:
                raise TraceNotFoundError(f"no script line {script_line_id}")
            s.briefing_id = line.briefing_id
            claims = (
                await conn.execute(
                    text(
                        "SELECT id, text, verdict, score, reason, rewrite_round, judged_at"
                        " FROM claims WHERE script_line_id = :id ORDER BY rewrite_round, id"
                    ),
                    {"id": script_line_id},
                )
            ).all()
            ids = [c.id for c in claims]
            cited: dict[UUID, list[SourceRef]] = {i: [] for i in ids}
            evidence: dict[UUID, list[EvidenceRef]] = {i: [] for i in ids}
            if ids:
                for r in await conn.execute(
                    text(
                        f"SELECT cs.claim_id, {_SOURCE_COLS} FROM claim_sources cs"
                        " JOIN sources s ON s.id = cs.source_id"
                        " WHERE cs.claim_id = ANY(:ids) ORDER BY s.outlet, s.url"
                    ),
                    {"ids": ids},
                ):
                    cited[r.claim_id].append(_source(r))
                for r in await conn.execute(
                    text(
                        f"SELECT e.claim_id, e.passage, e.score AS ev_score, {_SOURCE_COLS}"
                        " FROM claim_evidence e JOIN sources s ON s.id = e.source_id"
                        " WHERE e.claim_id = ANY(:ids) ORDER BY e.score DESC NULLS LAST"
                    ),
                    {"ids": ids},
                ):
                    evidence[r.claim_id].append(
                        EvidenceRef(source=_source(r), passage=r.passage, score=r.ev_score)
                    )
            spans = (
                await conn.execute(
                    text(
                        "SELECT id, started_at, payload FROM traces"
                        " WHERE component = :c AND event = :e AND payload->>'line_id' = :line"
                        " ORDER BY started_at"
                    ),
                    {"c": JUDGE_COMPONENT, "e": JUDGE_EVENT, "line": str(script_line_id)},
                )
            ).mappings()
            current = set(ids)
            history = [judgement_from_trace(r, current) for r in spans]
        s.set(claims=len(claims), judgements=len(history))
    return ClaimTrace(
        line_id=line.id,
        briefing_id=line.briefing_id,
        story_id=line.story_id,
        story_title=line.story_title,
        order=line.order,
        text=line.text,
        audio_start_ms=line.audio_start_ms,
        audio_end_ms=line.audio_end_ms,
        claims=[
            TracedClaim(
                id=c.id,
                text=c.text,
                verdict=c.verdict,
                score=c.score,
                reason=c.reason,
                rewrite_round=c.rewrite_round,
                judged_at=c.judged_at,
                cited=cited[c.id],
                evidence=evidence[c.id],
            )
            for c in claims
        ],
        history=history,
    )


async def rejection_log(
    briefing_id: UUID | None = None, limit: int = 100, include_rewrite: bool = True
) -> list[Rejection]:
    """Judgements that were not approved, newest first.

    ``current`` is false once a rewrite replaced the claim."""
    verdicts = list(REJECTING_OR_REWRITE if include_rewrite else REJECTING)
    with span(
        "archive", "rejection_log", briefing_id, limit=limit, include_rewrite=include_rewrite
    ) as s:
        async with get_engine().connect() as conn:
            where = "component = :c AND event = :e AND payload->>'verdict' = ANY(:v)"
            params: dict[str, Any] = {"c": JUDGE_COMPONENT, "e": JUDGE_EVENT, "v": verdicts}
            if briefing_id is not None:
                where += " AND briefing_id = :b"
                params["b"] = briefing_id
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT id, started_at, briefing_id, payload FROM traces"
                            f" WHERE {where} ORDER BY started_at DESC LIMIT :n"
                        ),
                        params | {"n": limit},
                    )
                )
                .mappings()
                .all()
            )
            line_ids = {i for r in rows if (i := line_id_of(r))}
            texts: dict[UUID, str] = {}
            if line_ids:
                for t in await conn.execute(
                    text("SELECT id, text FROM script_lines WHERE id = ANY(:ids)"),
                    {"ids": list(line_ids)},
                ):
                    texts[t.id] = t.text
            judged = [judgement_from_trace(r, set()) for r in rows]
            current = await _existing_claims(conn, [j.claim_id for j in judged if j.claim_id])
        out = []
        for r, j in zip(rows, judged, strict=True):
            lid = line_id_of(r)
            out.append(
                Rejection(
                    **(j.model_dump() | {"current": j.claim_id in current}),
                    briefing_id=r["briefing_id"],
                    line_id=lid,
                    line_text=texts.get(lid) if lid else None,
                )
            )
        s.set(rows=len(out))
    return out
