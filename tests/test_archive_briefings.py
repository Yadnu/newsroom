"""Briefing timeline: stage aggregation (pure) and the /archive/briefings routes (task 3.3)."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

import app.archive.briefings as briefings
from app.archive.briefings import (
    BriefingDetail,
    BriefingNotFoundError,
    BriefingSummary,
    LineSummary,
    stages_from_spans,
)
from app.main import app

T0 = datetime(2026, 11, 19, 9, 0, tzinfo=UTC)


def _span(
    component: str,
    parent: dict[str, Any] | None = None,
    latency: float = 100.0,
    cost: float | None = None,
    tokens: tuple[int, int] | None = None,
    error: str | None = None,
    at: int = 0,
) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "parent_id": parent["id"] if parent else None,
        "component": component,
        "started_at": T0 + timedelta(seconds=at),
        "latency_ms": latency,
        "cost_usd": cost,
        "tokens_in": tokens[0] if tokens else None,
        "tokens_out": tokens[1] if tokens else None,
        "error": error,
    }


def test_stages_charge_llm_calls_to_the_calling_component() -> None:
    rundown = _span("producer", latency=50, at=0)
    draft = _span("writer", latency=4000, at=1)
    d1 = _span("llm-gateway", draft, latency=3000, cost=0.002, tokens=(1000, 300), at=1)
    review = _span("editor", latency=9000, at=5)
    judge_a = _span("editor", review, latency=5000, at=5)  # nested editor step: not an entry
    judge_b = _span("editor", review, latency=6000, at=5)
    j1 = _span("llm-gateway", judge_a, latency=4500, cost=0.001, tokens=(4000, 100), at=5)
    j2 = _span("llm-gateway", judge_b, latency=5500, cost=0.001, tokens=(4000, 100), at=5)
    j3 = _span("llm-gateway", judge_b, latency=10, error="LLMProviderError: 429", at=6)
    orphan = _span("llm-gateway", latency=20, cost=0.0001, tokens=(5, 0), at=9)  # no parent
    spans = [j3, review, d1, rundown, judge_a, judge_b, j1, j2, draft, orphan]

    stages = {s.component: s for s in stages_from_spans(spans)}
    assert list(stages) == ["producer", "writer", "editor", "llm-gateway"]  # by first start

    w = stages["writer"]
    assert (w.steps, w.latency_ms, w.llm_calls, w.llm_ms) == (1, 4000, 1, 3000)
    assert w.cost_usd == pytest.approx(0.002) and (w.tokens_in, w.tokens_out) == (1000, 300)

    e = stages["editor"]
    assert (e.steps, e.latency_ms) == (1, 9000)  # only review_script is an entry span
    assert (e.llm_calls, e.llm_ms, e.errors) == (3, 10010, 1)  # summed: may exceed latency
    assert e.cost_usd == pytest.approx(0.002) and e.tokens_in == 8000

    p = stages["producer"]
    assert (p.steps, p.llm_calls, p.cost_usd) == (1, 0, 0.0)

    g = stages["llm-gateway"]  # a call with no owning component stands alone
    assert (g.steps, g.llm_calls, g.latency_ms) == (1, 1, 20)


def test_stages_tolerate_parent_cycles_and_empty_input() -> None:
    assert stages_from_spans([]) == []
    a = _span("llm-gateway")
    b = _span("llm-gateway", a)
    a["parent_id"] = b["id"]
    (stage,) = stages_from_spans([a, b])
    assert stage.component == "llm-gateway" and stage.llm_calls == 2


# ---- routes ---------------------------------------------------------------------------------


async def _get(path: str, **params: Any) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, params=params)


def _summary(bid: UUID) -> BriefingSummary:
    return BriefingSummary(
        id=bid,
        created_at=T0,
        status="judged",
        target_minutes=3,
        lines=2,
        verdicts={"approved": 3, "rejected": 1},
        cost_usd=0.004,
        tokens_in=9000,
        tokens_out=500,
        wall_ms=61000.0,
    )


async def test_briefings_route(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[int] = []
    bid = uuid4()

    async def fake(limit: int = 50) -> list[BriefingSummary]:
        seen.append(limit)
        return [_summary(bid)]

    monkeypatch.setattr(briefings, "list_briefings", fake)
    r = await _get("/archive/briefings", limit=5)
    assert r.status_code == 200 and seen == [5]
    (row,) = r.json()
    assert row["id"] == str(bid) and row["verdicts"] == {"approved": 3, "rejected": 1}
    assert (await _get("/archive/briefings")).status_code == 200 and seen[-1] == 50
    assert (await _get("/archive/briefings", limit=0)).status_code == 422
    assert (await _get("/archive/briefings", limit=201)).status_code == 422


async def test_briefing_detail_route_and_404(monkeypatch: pytest.MonkeyPatch) -> None:
    bid, line = uuid4(), uuid4()

    async def fake(briefing_id: UUID) -> BriefingDetail:
        if briefing_id != bid:
            raise BriefingNotFoundError(f"no briefing {briefing_id}")
        return BriefingDetail(
            briefing=_summary(bid),
            lines=[
                LineSummary(id=line, order=0, text="Acme ships.", story_title="Acme", verdicts={})
            ],
            stages=stages_from_spans([_span("writer")]),
        )

    monkeypatch.setattr(briefings, "briefing_detail", fake)
    body = (await _get(f"/archive/briefings/{bid}")).json()
    assert body["briefing"]["id"] == str(bid) and body["lines"][0]["id"] == str(line)
    assert body["stages"][0]["component"] == "writer"
    assert (await _get(f"/archive/briefings/{uuid4()}")).status_code == 404
    assert (await _get("/archive/briefings/not-a-uuid")).status_code == 422
