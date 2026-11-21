"""Retraction signals and recheck_sources() against mocked pages (task 6.2). No network, no DB."""

from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

import app.reporter.retract as retract
from app.archive import MemorySink
from app.reporter.retract import RetractionReport, recheck_sources, retraction_signal


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (404, ""),
        (410, "gone"),
        (200, "<p>Editor's note: this article has been retracted.</p>"),
        (200, "We have withdrawn this story after questions about its sourcing."),
        (200, "Retraction: an earlier version of this report was wrong."),
    ],
)
def test_signals_that_retract(status: int, body: str) -> None:
    assert retraction_signal(status, body)


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (403, "subscribe to read"),  # paywall
        (500, "server error"),
        (429, "slow down"),
        (200, "The journal retracted the paper last week, the researchers said."),
        (200, "Acme said the claim had been withdrawn by its accuser."),
        (200, "Correction: an earlier version misspelled the CEO's name."),  # a fix, not withdrawn
    ],
)
def test_signals_that_do_not(status: int, body: str) -> None:
    assert retraction_signal(status, body) is None


async def test_recheck_retracts_only_on_clear_signals(
    monkeypatch: pytest.MonkeyPatch, trace_sink: MemorySink
) -> None:
    pages = {
        "https://a.test/gone": (404, ""),
        "https://b.test/notice": (200, "This story has been removed by the publisher."),
        "https://c.test/fine": (200, "Acme shipped Nova."),
        "https://d.test/paywall": (403, "subscribe"),
    }

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "e.test":
            raise httpx.ConnectTimeout("slow")
        status, body = pages[str(req.url)]
        return httpx.Response(status, text=body)

    retracted: list[tuple[UUID, str]] = []

    async def fake_retract(ref: Any, reason: str) -> RetractionReport:
        retracted.append((ref, reason))
        return RetractionReport(ref, "", "", reason, False)

    monkeypatch.setattr(retract, "retract_source", fake_retract)
    ids = {u: uuid4() for u in [*pages, "https://e.test/timeout"]}
    report = await recheck_sources(
        transport=httpx.MockTransport(handler), sources=[(i, u) for u, i in ids.items()]
    )
    assert report.checked == 5 and report.unreachable == 2  # 403 and timeout: kept, not retracted
    assert {r for r, _ in retracted} == {ids["https://a.test/gone"], ids["https://b.test/notice"]}
    reasons = dict(retracted)
    assert reasons[ids["https://a.test/gone"]] == "page gone (HTTP 404)"
    span = next(t for t in trace_sink.traces if t.event == "recheck_sources")
    assert span.payload["retracted"] == 2


def test_parse_ref() -> None:
    i = uuid4()
    assert retract.parse_ref(str(i)) == i
    assert retract.parse_ref(" https://a.test/x ") == "https://a.test/x"
