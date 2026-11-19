"""``search_live()``: fresh sources for on-air answers (task 5.4, decisions 0003 and 0021).

Tavily news search -> full text from Tavily's ``raw_content`` or, when that is short, Firecrawl ->
stored as ``sources`` rows (deduped by URL and content hash) -> ``LiveSource`` refs.

URLs already in ``sources`` are reused without fetching again, and identical queries are cached for
``reporter_search_cache_s``. Everything fails soft: no key, an HTTP error or a timeout logs and
returns what it has (often ``[]``). Fetched text is untrusted data; the Writer escapes it.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from sqlalchemy import text

from app.archive import span
from app.config import Settings, get_settings
from app.db.session import get_engine
from app.log import get_logger
from app.reporter.ingest import NewSource, insert_new_sources
from app.reporter.parse import content_hash, normalize_url

TAVILY_URL = "https://api.tavily.com/search"
FIRECRAWL_URL = "https://api.firecrawl.dev/v1/scrape"
MIN_SNIPPET_CHARS = 300  # below this, a result without full text is dropped

OUTLETS = {
    "techcrunch.com": "TechCrunch",
    "theverge.com": "The Verge",
    "wired.com": "Wired",
    "arstechnica.com": "Ars Technica",
    "bbc.co.uk": "BBC News",
    "bbc.com": "BBC News",
    "reuters.com": "Reuters",
    "apnews.com": "AP News",
    "bloomberg.com": "Bloomberg",
    "cnbc.com": "CNBC",
    "nytimes.com": "The New York Times",
    "theguardian.com": "The Guardian",
    "ft.com": "Financial Times",
    "wsj.com": "The Wall Street Journal",
    "engadget.com": "Engadget",
    "zdnet.com": "ZDNET",
    "theregister.com": "The Register",
    "siliconangle.com": "SiliconANGLE",
    "the-decoder.com": "The Decoder",
    "venturebeat.com": "VentureBeat",
    "cnn.com": "CNN",
    "axios.com": "Axios",
}

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class LiveSource:
    id: UUID
    url: str
    outlet: str
    title: str
    published_at: datetime | None


@dataclass(frozen=True, slots=True)
class _Hit:
    url: str
    title: str
    text: str
    published_at: datetime | None


Lookup = Callable[[Sequence[str]], Awaitable[dict[str, LiveSource]]]
Store = Callable[[Sequence[NewSource]], Awaitable[int]]

_cache: dict[str, tuple[float, list[LiveSource]]] = {}


def clear_cache() -> None:
    _cache.clear()


def outlet_for(url: str) -> str:
    host = urlsplit(url).hostname or ""
    host = host.removeprefix("www.")
    for domain, name in OUTLETS.items():
        if host == domain or host.endswith("." + domain):
            return name
    return host or "unknown"


def _date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    for parse in (
        datetime.fromisoformat,
        lambda v: datetime.strptime(v, "%a, %d %b %Y %H:%M:%S %Z"),
    ):
        try:
            d = parse(value.replace("Z", "+00:00"))
        except ValueError:
            continue
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    return None


async def sources_by_url(urls: Sequence[str]) -> dict[str, LiveSource]:
    if not urls:
        return {}
    async with get_engine().connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT id, url, outlet, title, published_at FROM sources"
                " WHERE url = ANY(:u) AND NOT retracted"
            ),
            {"u": list(urls)},
        )
        return {r.url: LiveSource(r.id, r.url, r.outlet, r.title, r.published_at) for r in rows}


async def _tavily(
    client: httpx.AsyncClient, key: str, query: str, settings: Settings, max_results: int, days: int
) -> list[dict[str, Any]]:
    resp = await client.post(
        TAVILY_URL,
        headers={"Authorization": f"Bearer {key}"},
        json={
            "query": query,
            "topic": "news",
            "days": days,
            "max_results": max_results,
            "search_depth": "basic",
            "include_raw_content": True,
        },
    )
    if resp.status_code >= 400:
        raise httpx.HTTPStatusError(
            f"Tavily HTTP {resp.status_code}", request=resp.request, response=resp
        )
    results = resp.json().get("results") or []
    return [r for r in results if isinstance(r, dict)]


async def _firecrawl(client: httpx.AsyncClient, key: str, url: str) -> str:
    with span("reporter", "fetch_page", url=url) as s:
        try:
            resp = await client.post(
                FIRECRAWL_URL,
                headers={"Authorization": f"Bearer {key}"},
                json={"url": url, "formats": ["markdown"], "onlyMainContent": True},
            )
        except httpx.HTTPError as e:
            s.set(error=type(e).__name__)
            return ""
        s.set(status=resp.status_code)
        if resp.status_code >= 400:
            return ""
        data = resp.json().get("data") or {}
        markdown = data.get("markdown") if isinstance(data, dict) else None
        out = markdown.strip() if isinstance(markdown, str) else ""
        s.set(chars=len(out))
        return out


async def search_live(
    query: str,
    *,
    max_results: int | None = None,
    days: int | None = None,
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    store: Store = insert_new_sources,
    lookup: Lookup = sources_by_url,
) -> list[LiveSource]:
    """Fresh news sources for ``query``, stored and ready to cite. Provider errors never raise."""
    settings = settings or get_settings()
    max_results = max_results or settings.reporter_search_max_results
    days = days or settings.reporter_search_days
    cache_key = " ".join(query.lower().split()) + f"|{max_results}|{days}"
    started = time.perf_counter()
    with span("reporter", "search_live", query=query[:200], max_results=max_results) as s:
        cached = _cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < settings.reporter_search_cache_s:
            s.set(cached=True, results=len(cached[1]))
            return list(cached[1])
        key = settings.tavily_api_key.get_secret_value() if settings.tavily_api_key else ""
        if not key:
            log.warning("reporter.search_not_configured")
            s.set(error="no key")
            return []
        timeout = httpx.Timeout(settings.reporter_search_timeout_s)
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            try:
                results = await _tavily(client, key, query, settings, max_results, days)
            except (httpx.HTTPError, ValueError) as e:
                log.warning("reporter.search_failed", error=type(e).__name__)
                s.set(error=type(e).__name__)
                return []
            hits: list[_Hit] = []
            for r in results:
                url = r.get("url")
                if not isinstance(url, str) or urlsplit(url).scheme not in ("http", "https"):
                    continue
                raw = r.get("raw_content") if isinstance(r.get("raw_content"), str) else ""
                snippet = r.get("content") if isinstance(r.get("content"), str) else ""
                hits.append(
                    _Hit(
                        normalize_url(url),
                        str(r.get("title") or "").strip(),
                        (raw or "").strip() or (snippet or "").strip(),
                        _date(r.get("published_date")),
                    )
                )
            known = await lookup([h.url for h in hits])
            fresh = [h for h in hits if h.url not in known]
            fc_key = (
                settings.firecrawl_api_key.get_secret_value() if settings.firecrawl_api_key else ""
            )
            short = [h for h in fresh if len(h.text) < settings.reporter_search_min_chars]
            fetched: dict[str, str] = {}
            if fc_key and short:
                pages = await asyncio.gather(*(_firecrawl(client, fc_key, h.url) for h in short))
                fetched = {h.url: p for h, p in zip(short, pages, strict=True) if p}
        rows: list[NewSource] = []
        for h in fresh:
            body = fetched.get(h.url) or h.text
            if len(body) < MIN_SNIPPET_CHARS:
                continue
            body = body[: settings.reporter_fetch_max_chars]
            title = h.title or outlet_for(h.url)
            rows.append(
                NewSource(
                    url=h.url,
                    outlet=outlet_for(h.url),
                    title=title,
                    content=body,
                    content_hash=content_hash(title, body),
                    trust_score=settings.reporter_search_trust,
                    published_at=h.published_at,
                )
            )
        stored = await store(rows) if rows else 0
        found = await lookup([h.url for h in hits])  # read back ids in result order
        out = [found[h.url] for h in hits if h.url in found]
        s.set(
            results=len(results),
            reused=len(known),
            fetched=len(fetched),
            stored=stored,
            returned=len(out),
            ms=round((time.perf_counter() - started) * 1000),
        )
        _cache[cache_key] = (time.monotonic(), out)
        return out
