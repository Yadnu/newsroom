---
id: reporter
type: component
status: in-progress
phase: 1
code: app/reporter/
depends_on: [data-model, llm-gateway, archive]
feeds: [producer]
decisions: [0003]
---

# reporter

Fetches news from the internet, dedupes it, and clusters sources into stories.

## Contract

- `async def ingest_feeds(feeds: Sequence[FeedConfig] | None = None, *, transport=None, store=insert_new_sources) -> IngestReport`:
  pull the configured RSS/Atom feeds (`Settings.reporter_feeds`) and store new `sources`.
  `IngestReport`: feeds_total, feeds_failed, feeds_not_modified, entries_seen, new_sources,
  duplicates, errors (feed url -> reason).
- `async def insert_new_sources(rows: Sequence[NewSource]) -> int`: `INSERT ... ON CONFLICT DO NOTHING`
  against the unique `url` and `content_hash`. Returns the number of rows inserted.
- Scheduled job: `app/worker.py` `WorkerSettings` (ARQ) runs `ingest_job` on a cron every
  `reporter_ingest_every_minutes` (default 15), at startup, unique. Run with `uv run arq app.worker.WorkerSettings`.
  One-off run: `uv run python -m app.reporter`.
- Planned: `async def cluster_stories(window_hours: int = 24) -> list[Story]` (task 1.5).
- Planned: `async def search_live(query: str) -> list[Source]` (Tavily/Exa + Firecrawl, task 5.4).
- Every `Source` carries url, outlet, trust_score, published_at, content, content_hash.

## Invariants

- Never store the same `content_hash` twice. Never store the same normalized URL twice.
- `content_hash` = sha256 of lowercased, whitespace-collapsed `title + "\n" + content`.
- URLs are normalized: lowercase scheme and host, default port dropped, fragment dropped,
  tracking params (`utm_*`, fbclid, gclid, ...) removed.
- Fetched text is stored as plain text (HTML stripped, script/style dropped) and never interpreted as instructions.
- Every story has at least one source; stories with 2+ outlets are preferred by Producer.
- One feed failing never stops the others. A store failure fails the run.

## Current state

RSS ingest done (task 1.4): `parse.py` (feedparser, HTML to text, normalization, hash) and
`ingest.py` (concurrent httpx fetch, conditional GET by ETag/Last-Modified cached per process and
saved only after a successful store, in-run dedupe, Postgres insert). Spans: `reporter/ingest_feeds`
with a child `reporter/fetch_feed` per feed. Default feeds are 6 AI/tech outlets with a uniform
trust_score of 0.5 (placeholder). Live run on 2026-11-16: 91 sources from 6 outlets, a re-run
inserted 0. Content is the feed body only: often a summary of about 100 chars, and full text for
some outlets (capped at 20k chars). Embeddings are not set at ingest; that is for task 1.5.

## Open questions

- (none)

## Changelog

- 2026-11-16: node created from the design doc.
- 2026-11-16: empty package scaffolded (task 0.1).
- 2026-11-16: RSS ingest with url/content_hash dedupe, ARQ cron job (task 1.4).
