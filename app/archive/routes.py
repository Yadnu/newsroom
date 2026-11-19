"""HTTP routes for the Archive read API (used by the web Player and Archive dashboard)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from app.archive import briefings, trace
from app.archive.briefings import BriefingDetail, BriefingNotFoundError, BriefingSummary
from app.archive.trace import ClaimTrace, Rejection, TraceNotFoundError

router = APIRouter(prefix="/archive", tags=["archive"])


@router.get("/briefings")
async def get_briefings(limit: Annotated[int, Query(ge=1, le=200)] = 50) -> list[BriefingSummary]:
    """Briefings, newest first, with claim verdict counts, cost and wall time."""
    return await briefings.list_briefings(limit)


@router.get("/briefings/{briefing_id}")
async def get_briefing(briefing_id: UUID) -> BriefingDetail:
    """One briefing: its script lines with verdict counts, and latency and cost per stage."""
    try:
        return await briefings.briefing_detail(briefing_id)
    except BriefingNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/lines/{line_id}/trace")
async def get_claim_trace(line_id: UUID) -> ClaimTrace:
    """A script line with its claims, verdicts, cited sources, evidence and judgement history."""
    try:
        return await trace.claim_trace(line_id)
    except TraceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/rejections")
async def get_rejections(
    briefing_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    include_rewrite: bool = True,
) -> list[Rejection]:
    """Editor judgements that were not approved, newest first."""
    return await trace.rejection_log(briefing_id, limit=limit, include_rewrite=include_rewrite)
