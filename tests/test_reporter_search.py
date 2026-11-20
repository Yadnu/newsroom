"""reporter.search_live() against mocked Tavily and Firecrawl (task 5.4). No network, no DB."""

import json
from collections.abc import Sequence
from typing import Any
from uuid import uuid4

import httpx
import pytest

from app.archive import MemorySink
from app.config import Settings
from app.reporter.ingest import NewSource
from app.reporter.search import LiveSource, clear_cache, outlet_for, search_live

LONG = "Nvidia named Colette Kress interim chief executive. " * 40  # ~2000 chars
SHORT = "Nvidia said its earnings date is Feb 25."  # needs Firecrawl


def settings(**kw: Any) -> Settings:
    base: dict[str, Any] = {
        "tavily_api_key": "tvly-test",
        "firecrawl_api_key": "fc-test",
        "reporter_search_cache_s": 600,
    }
    return Settings(_env_file=None, **(base | kw))  # type: ignore[call-arg]


class World:
    """Fake Tavily + Firecrawl + sources table."""

    def __init__(self, results: list[dict[str, Any]], page: str = LONG, fc_status: int = 200):
        self.results = results
        self.page = page
        self.fc_status = fc_status
        self.requests: list[tuple[str, dict[str, Any], dict[str, str]]] = []
        self.table: dict[str, LiveSource] = {}
        self.stored: list[NewSource] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        self.requests.append((req.url.host or "", body, dict(req.headers)))
        if req.url.host == "api.tavily.com":
            return httpx.Response(200, json={"results": self.results})
        if self.fc_status >= 400:
            return httpx.Response(self.fc_status, json={"error": "blocked"})
        return httpx.Response(200, json={"success": True, "data": {"markdown": self.page}})

    async def store(self, rows: Sequence[NewSource]) -> int:
        self.stored.extend(rows)
        for r in rows:
            self.table[r.url] = LiveSource(uuid4(), r.url, r.outlet, r.title, r.published_at)
        return len(rows)

    async def lookup(self, urls: Sequence[str]) -> dict[str, LiveSource]:
        return {u: self.table[u] for u in urls if u in self.table}

    async def run(self, query: str = "nvidia ceo", **kw: Any) -> list[LiveSource]:
        return await search_live(
            query,
            settings=settings(**kw),
            transport=httpx.MockTransport(self),
            store=self.store,
            lookup=self.lookup,
        )

    def hosts(self) -> list[str]:
        return [h for h, _, _ in self.requests]


def result(url: str, raw: str | None = LONG, **kw: Any) -> dict[str, Any]:
    return {
        "url": url,
        "title": kw.get("title", "Nvidia names interim CEO"),
        "content": kw.get("content", "snippet"),
        "raw_content": raw,
        "published_date": kw.get("date", "Wed, 19 Nov 2026 10:00:00 GMT"),
    }


@pytest.fixture(autouse=True)
def fresh_cache() -> None:
    clear_cache()


async def test_tavily_request_and_long_text_stored_directly(trace_sink: MemorySink) -> None:
    w = World([result("https://www.reuters.com/tech/nvidia?utm_source=x")])
    (src,) = await w.run()
    host, body, headers = w.requests[0]
    assert host == "api.tavily.com" and headers["authorization"] == "Bearer tvly-test"
    assert (body["topic"], body["days"], body["include_raw_content"]) == ("news", 7, True)
    assert body["max_results"] == 5  # reporter_search_max_results
    assert w.hosts() == ["api.tavily.com"]  # no Firecrawl: raw_content was long enough
    assert (src.outlet, src.url) == ("Reuters", "https://www.reuters.com/tech/nvidia")
    assert src.published_at is not None and src.published_at.day == 19
    (row,) = w.stored
    assert row.trust_score == 0.5 and row.content.startswith("Nvidia named")
    span = next(t for t in trace_sink.traces if t.event == "search_live")
    assert span.payload["stored"] == 1 and span.payload["fetched"] == 0


async def test_short_text_is_fetched_with_firecrawl() -> None:
    w = World([result("https://techcrunch.com/a", raw=SHORT)])
    (src,) = await w.run()
    assert w.hosts() == ["api.tavily.com", "api.firecrawl.dev"]
    _, body, headers = w.requests[1]
    assert body["url"] == "https://techcrunch.com/a" and body["formats"] == ["markdown"]
    assert headers["authorization"] == "Bearer fc-test"
    assert w.stored[0].content.startswith("Nvidia named") and src.outlet == "TechCrunch"


async def test_firecrawl_failure_keeps_long_snippets_and_drops_short_ones() -> None:
    medium = "Nvidia said its earnings call will be on February 25 after the close. " * 6
    w = World(
        [result("https://a.test/1", raw=medium), result("https://b.test/2", raw=SHORT)],
        fc_status=403,
    )
    found = await w.run()
    assert [s.url for s in found] == ["https://a.test/1"]  # 400+ chars kept, 40 chars dropped
    assert w.stored[0].outlet == "a.test"


async def test_known_urls_are_reused_without_fetching() -> None:
    w = World([result("https://techcrunch.com/old", raw=SHORT)])
    old = LiveSource(uuid4(), "https://techcrunch.com/old", "TechCrunch", "Old", None)
    w.table[old.url] = old
    assert await w.run() == [old]
    assert w.hosts() == ["api.tavily.com"] and w.stored == []


async def test_identical_queries_are_cached() -> None:
    w = World([result("https://a.test/1")])
    first = await w.run("Nvidia  CEO")
    second = await w.run("nvidia ceo")
    assert first == second and w.hosts() == ["api.tavily.com"]
    await w.run("nvidia ceo", reporter_search_cache_s=0)  # cache off: searches again
    assert w.hosts().count("api.tavily.com") == 2


async def test_no_key_or_provider_error_returns_nothing(trace_sink: MemorySink) -> None:
    w = World([result("https://a.test/1")])
    assert await w.run(tavily_api_key=None) == [] and w.requests == []

    def down(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "down"})

    found = await search_live(
        "nvidia", settings=settings(), transport=httpx.MockTransport(down), lookup=w.lookup
    )
    assert found == []
    errors = [t.payload.get("error") for t in trace_sink.traces if t.event == "search_live"]
    assert errors == ["no key", "HTTPStatusError"]


async def test_no_firecrawl_key_uses_tavily_text_only() -> None:
    w = World([result("https://a.test/1", raw=SHORT, content="x" * 500)])
    found = await w.run(firecrawl_api_key=None)
    assert w.hosts() == ["api.tavily.com"] and found == []  # 40-char raw text beats the snippet


async def test_non_http_urls_are_skipped() -> None:
    w = World([result("javascript:alert(1)"), result("ftp://a.test/x"), result("https://ok.test/")])
    assert [s.url for s in await w.run()] == ["https://ok.test/"]


def test_outlet_for_domains() -> None:
    assert outlet_for("https://www.theverge.com/x") == "The Verge"
    assert outlet_for("https://edition.cnn.com/x") == "CNN"
    assert outlet_for("https://news.example.org/a") == "news.example.org"
