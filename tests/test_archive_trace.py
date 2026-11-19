from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

import app.archive.trace as trace
from app.archive.trace import (
    ClaimTrace,
    Rejection,
    TraceNotFoundError,
    judgement_from_trace,
    line_id_of,
)
from app.main import app

AT = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


def _row(payload: Any) -> dict[str, Any]:
    return {"id": uuid4(), "started_at": AT, "payload": payload}


def test_judgement_from_full_payload() -> None:
    claim, line = uuid4(), uuid4()
    row = _row(
        {
            "claim_id": str(claim),
            "line_id": str(line),
            "claim": "Acme ships.",
            "verdict": "rejected",
            "score": 0.4,
            "reason": "supported: no",
            "checks": {"supported": False, "faithful": True},
        }
    )
    j = judgement_from_trace(row, {claim})
    assert (j.claim_id, j.verdict, j.score, j.current) == (claim, "rejected", 0.4, True)
    assert j.checks == {"supported": False, "faithful": True} and j.at == AT
    assert line_id_of(row) == line


def test_judgement_tolerates_old_and_malformed_payloads() -> None:
    old = _row({"claim_id": str(uuid4()), "verdict": "rewrite"})  # before line_id and claim text
    j = judgement_from_trace(old, set())
    assert j.claim == "" and j.reason == "" and j.checks == {} and j.score is None
    assert j.current is False and line_id_of(old) is None

    junk = _row({"claim_id": "not-a-uuid", "line_id": 7, "score": "high", "checks": ["x"]})
    j = judgement_from_trace(junk, set())
    assert j.claim_id is None and j.score is None and j.checks == {} and j.verdict == "unknown"
    assert line_id_of(junk) is None
    assert judgement_from_trace(_row(None), set()).verdict == "unknown"


# ---- routes ---------------------------------------------------------------------------------


async def _get(path: str, **params: Any) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, params=params)


def _trace(line_id: UUID) -> ClaimTrace:
    return ClaimTrace(
        line_id=line_id,
        briefing_id=uuid4(),
        story_id=None,
        story_title=None,
        order=0,
        text="A line.",
        audio_start_ms=None,
        audio_end_ms=None,
        claims=[],
        history=[],
    )


async def test_trace_route(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(line_id: UUID) -> ClaimTrace:
        return _trace(line_id)

    monkeypatch.setattr(trace, "claim_trace", fake)
    line = uuid4()
    resp = await _get(f"/archive/lines/{line}/trace")
    assert resp.status_code == 200
    assert resp.json()["line_id"] == str(line) and resp.json()["text"] == "A line."


async def test_trace_route_404_and_bad_id(monkeypatch: pytest.MonkeyPatch) -> None:
    async def missing(line_id: UUID) -> ClaimTrace:
        raise TraceNotFoundError(f"no script line {line_id}")

    monkeypatch.setattr(trace, "claim_trace", missing)
    assert (await _get(f"/archive/lines/{uuid4()}/trace")).status_code == 404
    assert (await _get("/archive/lines/nope/trace")).status_code == 422


async def test_rejections_route_passes_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def fake(
        briefing_id: UUID | None = None, limit: int = 100, include_rewrite: bool = True
    ) -> list[Rejection]:
        seen.update(briefing_id=briefing_id, limit=limit, include_rewrite=include_rewrite)
        return [
            Rejection(
                trace_id=uuid4(),
                at=AT,
                claim_id=uuid4(),
                claim="X.",
                verdict="rejected",
                score=0.1,
                reason="no",
                checks={},
                current=False,
                briefing_id=briefing_id,
                line_id=None,
                line_text=None,
            )
        ]

    monkeypatch.setattr(trace, "rejection_log", fake)
    b = uuid4()
    resp = await _get("/archive/rejections", briefing_id=str(b), limit=5, include_rewrite="false")
    assert resp.status_code == 200
    assert seen == {"briefing_id": b, "limit": 5, "include_rewrite": False}
    assert resp.json()[0]["verdict"] == "rejected"

    await _get("/archive/rejections")
    assert seen == {"briefing_id": None, "limit": 100, "include_rewrite": True}
    assert (await _get("/archive/rejections", limit=0)).status_code == 422
    assert (await _get("/archive/rejections", limit=501)).status_code == 422
