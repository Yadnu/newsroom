"""Source retraction (task 6.2, decision 0023).

``retract_source`` marks a source retracted and, in the same transaction, has the Standards Desk
record every claim that relied on it (``flag_retraction``). ``recheck_sources`` re-fetches sources
behind recent briefings and retracts only on clear signals: HTTP 404/410, or a retraction notice in
the page. A 403, a 5xx or a timeout is never a retraction (paywalls and outages are common).
"""

import asyncio
import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.archive import span
from app.config import get_settings
from app.db.models import utcnow
from app.db.session import get_engine
from app.log import get_logger
from app.reporter.parse import normalize_url
from app.standards_desk.corrections import Flagged, flag_retraction

log = get_logger(__name__)

GONE = (404, 410)
# Publisher notices that withdraw the article itself. Each needs the whole phrase, so a story that
# reports on someone else's retraction ("the journal retracted the paper") does not match.
RETRACTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bthis (article|story|report|piece|post) (has been|was) "
        r"(retracted|withdrawn|removed)\b",
        r"\b(we|the \w+) (have|has) (retracted|withdrawn|removed) this "
        r"(article|story|report|piece)\b",
        r"\beditor'?s note:.{0,80}\b(retracted|withdrawn|removed)\b.{0,40}"
        r"\b(article|story|report)\b",
        r"\bretraction:\s",
    )
]


class SourceNotFoundError(LookupError):
    """No source with that id or URL."""


@dataclass(frozen=True, slots=True)
class RetractionReport:
    source_id: UUID
    url: str
    outlet: str
    reason: str
    already: bool  # it was retracted before: nothing changed
    briefings: tuple[Flagged, ...] = ()

    @property
    def on_air(self) -> int:
        return sum(b.on_air for b in self.briefings)


async def _find(conn: AsyncConnection, ref: str | UUID) -> Row[Any] | None:
    q = (
        "SELECT id, url, outlet, retracted, retraction_reason FROM sources WHERE id = :v"
        if isinstance(ref, UUID)
        else "SELECT id, url, outlet, retracted, retraction_reason FROM sources"
        " WHERE url = :v OR url = :n"
    )
    params = {"v": ref} if isinstance(ref, UUID) else {"v": ref, "n": normalize_url(ref)}
    return (await conn.execute(text(q), params)).first()


def parse_ref(ref: str) -> str | UUID:
    try:
        return UUID(ref)
    except ValueError:
        return ref.strip()


async def retract_source(ref: str | UUID, reason: str) -> RetractionReport:
    """Retract a source by id or URL and flag the briefings that used it. Idempotent."""
    reason = reason.strip() or "retracted"
    with span("reporter", "retract_source", ref=str(ref), reason=reason) as s:
        async with get_engine().begin() as conn:
            row = await _find(conn, ref)
            if row is None:
                raise SourceNotFoundError(f"no source {ref}")
            src = row
            if src.retracted:
                s.set(source_id=src.id, already=True)
                return RetractionReport(
                    src.id,
                    src.url,
                    src.outlet,
                    src.retraction_reason or reason,
                    True,
                )
            await conn.execute(
                text(
                    "UPDATE sources SET retracted = true, retracted_at = :at,"
                    " retraction_reason = :r WHERE id = :id"
                ),
                {"at": utcnow(), "r": reason, "id": src.id},
            )
            flagged = await flag_retraction(conn, src.id)
        report = RetractionReport(
            src.id,
            src.url,
            src.outlet,
            reason,
            False,
            tuple(flagged),
        )
        s.set(
            source_id=report.source_id,
            already=False,
            briefings=len(flagged),
            on_air=report.on_air,
        )
    log.info("reporter.retracted", source=str(report.source_id), briefings=len(flagged))
    return report


def retraction_signal(status: int, body: str) -> str | None:
    """Why a fetched page means the source is withdrawn, or ``None``."""
    if status in GONE:
        return f"page gone (HTTP {status})"
    if status >= 400:
        return None
    for p in RETRACTION_PATTERNS:
        if m := p.search(body):
            return f"retraction notice: {m.group(0)!r}"
    return None


@dataclass(slots=True)
class RecheckReport:
    checked: int = 0
    unreachable: int = 0
    retracted: list[RetractionReport] = field(default_factory=list)


async def recent_cited_sources(hours: int, limit: int) -> list[tuple[UUID, str]]:
    """Live sources that claims in briefings from the last ``hours`` cited or were judged on."""
    since = utcnow() - timedelta(hours=hours)
    async with get_engine().connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT DISTINCT s.id, s.url, s.fetched_at FROM sources s"
                " JOIN (SELECT claim_id, source_id FROM claim_sources"
                "       UNION SELECT claim_id, source_id FROM claim_evidence) x"
                "   ON x.source_id = s.id"
                " JOIN claims c ON c.id = x.claim_id"
                " JOIN script_lines l ON l.id = c.script_line_id"
                " JOIN briefings b ON b.id = l.briefing_id"
                " WHERE NOT s.retracted AND b.created_at >= :since"
                " ORDER BY s.fetched_at DESC LIMIT :n"
            ),
            {"since": since, "n": limit},
        )
        return [(r.id, r.url) for r in rows]


async def recheck_sources(
    hours: int | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    sources: list[tuple[UUID, str]] | None = None,
) -> RecheckReport:
    """Re-fetch recently cited sources and retract the ones that were withdrawn."""
    settings = get_settings()
    hours = settings.reporter_recheck_hours if hours is None else hours
    report = RecheckReport()
    with span("reporter", "recheck_sources", hours=hours) as s:
        todo = sources
        if todo is None:
            todo = await recent_cited_sources(hours, settings.reporter_recheck_max)
        sem = asyncio.Semaphore(settings.reporter_max_concurrency)
        async with httpx.AsyncClient(
            timeout=settings.reporter_fetch_timeout_s,
            transport=transport,
            follow_redirects=True,
            headers={"User-Agent": settings.reporter_user_agent},
        ) as client:

            async def one(source_id: UUID, url: str) -> tuple[UUID, str | None, bool]:
                async with sem:
                    with span("reporter", "recheck_page", url=url) as ps:
                        try:
                            resp = await client.get(url)
                        except httpx.HTTPError as e:
                            ps.set(error=type(e).__name__)
                            return source_id, None, True
                        signal = retraction_signal(resp.status_code, resp.text)
                        ps.set(status=resp.status_code, signal=signal)
                        return source_id, signal, resp.status_code >= 400

            results = await asyncio.gather(*(one(i, u) for i, u in todo))
        for source_id, signal, failed in results:
            report.checked += 1
            report.unreachable += failed and signal is None
            if signal:
                report.retracted.append(await retract_source(source_id, signal))
        s.set(
            checked=report.checked,
            unreachable=report.unreachable,
            retracted=len(report.retracted),
        )
    return report
