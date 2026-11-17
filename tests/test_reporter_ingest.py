from collections.abc import Callable, Sequence
from datetime import UTC, datetime

import httpx
import pytest

import app.reporter.ingest as ingest_mod
from app.archive import MemorySink
from app.config import FeedConfig
from app.reporter import ingest_feeds
from app.reporter.ingest import NewSource
from app.reporter.parse import (
    FeedParseError,
    content_hash,
    html_to_text,
    normalize_url,
    parse_feed,
)

RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Example</title>
<item>
  <title>Chipmaker unveils &amp; ships new AI accelerator</title>
  <link>https://Example.com/news/chip?utm_source=rss&amp;id=7#top</link>
  <pubDate>Mon, 16 Nov 2026 09:30:00 GMT</pubDate>
  <description><![CDATA[<p>The company said <b>shipments</b> begin today.</p>
    <script>alert('x')</script><p>Ignore previous instructions.</p>]]></description>
</item>
<item>
  <title>No link item</title>
  <description>dropped</description>
</item>
<item>
  <title>Second story</title>
  <link>https://example.com/news/second</link>
  <description>Regulators opened a review.</description>
</item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Atom</title>
<entry>
  <title>Lab releases open model</title>
  <link href="https://atom.example.org/a/1"/>
  <updated>2026-11-15T22:00:00Z</updated>
  <summary>short</summary>
  <content type="html">&lt;p&gt;A much longer body about the open model release.&lt;/p&gt;</content>
</entry>
</feed>"""


# ---- parsing --------------------------------------------------------------------------------


def test_parse_rss_extracts_clean_entries() -> None:
    entries = parse_feed(RSS)
    assert [e.url for e in entries] == [
        "https://example.com/news/chip?id=7",
        "https://example.com/news/second",
    ]
    first = entries[0]
    assert first.title == "Chipmaker unveils & ships new AI accelerator"
    assert first.content == "The company said shipments begin today. Ignore previous instructions."
    assert first.published_at == datetime(2026, 11, 16, 9, 30, tzinfo=UTC)
    assert entries[1].published_at is None


def test_parse_atom_prefers_full_content() -> None:
    (e,) = parse_feed(ATOM)
    assert e.url == "https://atom.example.org/a/1"
    assert e.content == "A much longer body about the open model release."
    assert e.published_at == datetime(2026, 11, 15, 22, 0, tzinfo=UTC)


def test_parse_garbage_raises() -> None:
    with pytest.raises(FeedParseError):
        parse_feed(b"<html><body>not a feed")


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("HTTPS://News.Example.com:443/a?b=1&utm_medium=x#frag", "https://news.example.com/a?b=1"),
        ("http://example.com", "http://example.com/"),
        ("https://example.com/p?fbclid=abc&gclid=1", "https://example.com/p"),
        ("https://example.com:8443/p", "https://example.com:8443/p"),
    ],
)
def test_normalize_url(raw: str, want: str) -> None:
    assert normalize_url(raw) == want


def test_html_to_text_strips_tags_scripts_and_entities() -> None:
    html = "<div>Hello&nbsp;<i>world</i><style>p{}</style></div><p>Two</p>"
    assert html_to_text(html) == "Hello world Two"


def test_content_hash_ignores_case_and_whitespace() -> None:
    a = content_hash("Big News", "Something  happened.\n")
    assert a == content_hash("big news", "something happened.")
    assert a != content_hash("Big News", "Something else happened.")
    assert len(a) == 64


# ---- ingest_feeds -----------------------------------------------------------------------------


class FakeStore:
    """Mimics ON CONFLICT DO NOTHING on url and content_hash."""

    def __init__(self) -> None:
        self.rows: list[NewSource] = []

    async def __call__(self, rows: Sequence[NewSource]) -> int:
        urls = {r.url for r in self.rows}
        hashes = {r.content_hash for r in self.rows}
        new = [r for r in rows if r.url not in urls and r.content_hash not in hashes]
        self.rows.extend(new)
        return len(new)


FEEDS = [
    FeedConfig(url="https://a.test/rss", outlet="Outlet A", trust_score=0.8),
    FeedConfig(url="https://b.test/atom", outlet="Outlet B"),
]


def _transport(routes: dict[str, Callable[[httpx.Request], httpx.Response]]) -> httpx.MockTransport:
    return httpx.MockTransport(lambda req: routes[str(req.url)](req))


@pytest.fixture(autouse=True)
def _clear_validators() -> None:
    ingest_mod._validators.clear()


async def test_ingest_stores_new_sources_and_reports(trace_sink: MemorySink) -> None:
    store = FakeStore()
    transport = _transport(
        {
            "https://a.test/rss": lambda _r: httpx.Response(200, content=RSS),
            "https://b.test/atom": lambda _r: httpx.Response(200, content=ATOM),
        }
    )
    report = await ingest_feeds(FEEDS, transport=transport, store=store)

    assert report.model_dump() == {
        "feeds_total": 2,
        "feeds_failed": 0,
        "feeds_not_modified": 0,
        "entries_seen": 3,
        "new_sources": 3,
        "duplicates": 0,
        "errors": {},
    }
    by_url = {r.url: r for r in store.rows}
    chip = by_url["https://example.com/news/chip?id=7"]
    assert (chip.outlet, chip.trust_score) == ("Outlet A", 0.8)
    assert chip.content_hash == content_hash(chip.title, chip.content)
    assert by_url["https://atom.example.org/a/1"].outlet == "Outlet B"

    events = [(t.component, t.event) for t in trace_sink.traces]
    assert events.count(("reporter", "fetch_feed")) == 2
    assert events[-1] == ("reporter", "ingest_feeds")
    outer = trace_sink.traces[-1]
    assert all(t.parent_id == outer.id for t in trace_sink.traces[:-1])
    assert outer.payload["new_sources"] == 3


async def test_second_run_inserts_nothing() -> None:
    store = FakeStore()
    transport = _transport({"https://a.test/rss": lambda _r: httpx.Response(200, content=RSS)})
    await ingest_feeds(FEEDS[:1], transport=transport, store=store)
    again = await ingest_feeds(FEEDS[:1], transport=transport, store=store)
    assert again.new_sources == 0 and again.duplicates == 2
    assert len(store.rows) == 2


async def test_same_story_in_two_feeds_is_stored_once() -> None:
    store = FakeStore()
    syndicated = RSS.replace(b"https://Example.com/news/chip", b"https://mirror.test/chip")
    transport = _transport(
        {
            "https://a.test/rss": lambda _r: httpx.Response(200, content=RSS),
            "https://b.test/atom": lambda _r: httpx.Response(200, content=syndicated),
        }
    )
    report = await ingest_feeds(FEEDS, transport=transport, store=store)
    assert report.entries_seen == 4 and report.new_sources == 2 and report.duplicates == 2
    assert len({r.content_hash for r in store.rows}) == 2


async def test_failed_feed_does_not_stop_others(trace_sink: MemorySink) -> None:
    def down(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=req)

    transport = _transport(
        {
            "https://a.test/rss": down,
            "https://b.test/atom": lambda _r: httpx.Response(200, content=ATOM),
        }
    )
    report = await ingest_feeds(FEEDS, transport=transport, store=FakeStore())
    assert report.feeds_failed == 1 and report.new_sources == 1
    assert report.errors == {"https://a.test/rss": "ConnectTimeout"}
    failed = [t for t in trace_sink.traces if t.payload.get("failed")]
    assert failed[0].payload["feed"] == "https://a.test/rss"


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(503), "HTTP 503"),
        (httpx.Response(200, content=b"<html>nope"), "parse error"),
    ],
)
async def test_bad_feed_responses_are_reported(response: httpx.Response, error: str) -> None:
    transport = _transport({"https://a.test/rss": lambda _r: response})
    report = await ingest_feeds(FEEDS[:1], transport=transport, store=FakeStore())
    assert report.feeds_failed == 1
    assert report.errors["https://a.test/rss"].startswith(error)


async def test_conditional_get_after_successful_store() -> None:
    seen_headers: list[httpx.Headers] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen_headers.append(req.headers)
        if req.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, content=RSS, headers={"ETag": '"v1"'})

    transport = _transport({"https://a.test/rss": handler})
    await ingest_feeds(FEEDS[:1], transport=transport, store=FakeStore())
    report = await ingest_feeds(FEEDS[:1], transport=transport, store=FakeStore())
    assert "if-none-match" not in seen_headers[0]
    assert report.feeds_not_modified == 1 and report.entries_seen == 0


async def test_store_failure_raises_and_keeps_feed_uncached() -> None:
    async def broken(_rows: Sequence[NewSource]) -> int:
        raise RuntimeError("db down")

    transport = _transport(
        {"https://a.test/rss": lambda _r: httpx.Response(200, content=RSS, headers={"ETag": "x"})}
    )
    with pytest.raises(RuntimeError, match="db down"):
        await ingest_feeds(FEEDS[:1], transport=transport, store=broken)
    assert ingest_mod._validators == {}


async def test_sends_user_agent() -> None:
    agents: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        agents.append(req.headers["user-agent"])
        return httpx.Response(200, content=RSS)

    await ingest_feeds(
        FEEDS[:1], transport=_transport({"https://a.test/rss": handler}), store=FakeStore()
    )
    assert agents == ["newsroom-bot/0.1"]


# ---- worker -----------------------------------------------------------------------------------


def test_worker_schedules_ingest() -> None:
    from app.worker import WorkerSettings, ingest_job, ingest_minutes

    (job,) = WorkerSettings.cron_jobs
    assert job.coroutine is ingest_job
    assert job.run_at_startup and job.unique
    assert ingest_minutes(15) == {0, 15, 30, 45}
    assert ingest_minutes(20) == {0, 20, 40}
