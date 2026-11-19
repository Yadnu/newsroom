"""HTTP routes for the Archive read API (used by the web Player and Archive dashboard)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from app.archive import trace
from app.archive.trace import ClaimTrace, Rejection, TraceNotFoundError

router = APIRouter(prefix="/archive", tags=["archive"])


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
