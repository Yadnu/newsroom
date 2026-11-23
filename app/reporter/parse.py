"""Pure helpers: feed XML -> entries, URL normalization, HTML to text, content hashing.

Everything here treats fetched content as data. Nothing is evaluated or followed.
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser

MAX_CONTENT_CHARS = 20_000

_TRACKING_PARAMS = re.compile(r"^(utm_\w+|fbclid|gclid|mc_cid|mc_eid|cmpid|taid|guccounter)$", re.I)
_WS = re.compile(r"\s+")
_BLOCK_TAGS = frozenset(
    {"p", "br", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "blockquote"}
)
_SKIP_TAGS = frozenset({"script", "style", "noscript", "iframe", "svg"})


@dataclass(frozen=True, slots=True)
class FeedEntry:
    url: str
    title: str
    content: str
    published_at: datetime | None
    image_url: str | None = None  # publisher thumbnail from the feed (task 8.2)


class FeedParseError(Exception):
    pass


def normalize_url(url: str) -> str:
    """Canonical form for dedupe: lowercase scheme and host, no fragment, no tracking params."""
    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "https").lower()
    host = parts.netloc.lower()
    if (scheme, host.rsplit(":", 1)[-1]) in {("http", "80"), ("https", "443")}:
        host = host.rsplit(":", 1)[0]
    query = urlencode(
        [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not _TRACKING_PARAMS.match(k)
        ]
    )
    path = parts.path or "/"
    return urlunsplit((scheme, host, path, query, ""))


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.first_img: str | None = None
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "img" and self.first_img is None:
            self.first_img = dict(attrs).get("src")
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1
        elif tag in _BLOCK_TAGS:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return _WS.sub(" ", "".join(parser.parts)).strip()


def first_image_in_html(html: str) -> str | None:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return parser.first_img


MAX_IMAGE_URL = 2000


def _image_url(url: object) -> str | None:
    """An absolute http(s) URL of sane length, or None. Never fetched here: it is only stored."""
    if not isinstance(url, str):
        return None
    url = url.strip()
    if not url.startswith(("http://", "https://")) or len(url) > MAX_IMAGE_URL:
        return None
    return url


def entry_image(entry: Any) -> str | None:
    """The entry's thumbnail: media:thumbnail, then image media:content or enclosures, then the
    first <img> in the body."""
    for thumb in entry.get("media_thumbnail", []) or []:
        if url := _image_url(thumb.get("url")):
            return url
    for media in entry.get("media_content", []) or []:
        kind = str(media.get("medium") or media.get("type") or "image")
        if kind.startswith("image") and (url := _image_url(media.get("url"))):
            return url
    for link in [*(entry.get("enclosures", []) or []), *(entry.get("links", []) or [])]:
        if str(link.get("type", "")).startswith("image/") and (
            url := _image_url(link.get("href") or link.get("url"))
        ):
            return url
    return _image_url(first_image_in_html(_best_body(entry)))


def content_hash(title: str, content: str) -> str:
    """sha256 over case- and whitespace-normalized title + text. 64 hex chars."""
    norm = _WS.sub(" ", f"{title}\n{content}".lower()).strip()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def parse_feed(raw: bytes) -> list[FeedEntry]:
    parsed: Any = feedparser.parse(raw)
    if parsed.get("bozo") and not parsed.get("entries"):
        raise FeedParseError(type(parsed.get("bozo_exception")).__name__)
    entries: list[FeedEntry] = []
    for e in parsed.get("entries", []):
        link = e.get("link")
        if not link or not str(link).startswith(("http://", "https://")):
            continue
        title = html_to_text(str(e.get("title", "")))
        content = html_to_text(_best_body(e))[:MAX_CONTENT_CHARS]
        if not title and not content:
            continue
        entries.append(
            FeedEntry(
                url=normalize_url(str(link)),
                title=title or content[:120],
                content=content or title,
                published_at=_published(e),
                image_url=entry_image(e),
            )
        )
    return entries


def _best_body(entry: Any) -> str:
    bodies = [str(c.get("value", "")) for c in entry.get("content", []) or []]
    bodies.append(str(entry.get("summary", "")))
    return max(bodies, key=len)


def _published(entry: Any) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            try:
                return datetime(t[0], t[1], t[2], t[3], t[4], t[5], tzinfo=UTC)
            except (TypeError, ValueError):
                continue
    return None
