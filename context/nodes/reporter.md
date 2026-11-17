---
id: reporter
type: component
status: in-progress
phase: 1
code: app/reporter/
depends_on: [data-model, llm-gateway, archive]
feeds: [producer]
decisions: [0003, 0010]
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
  `reporter_ingest_every_minutes` (default 15), at startup, unique. The job runs ingest, then
  embed, then cluster. A missing Voyage key skips the embed step with a warning. Run with `uv run arq app.worker.WorkerSettings`.
  One-off run: `uv run python -m app.reporter`.
- `async def embed_pending_sources(limit: int = 5000) -> int`: embed non-retracted sources with a null
  `embedding` (`title + content`, capped at `reporter_embed_max_chars`) through `llm.embed(..., "document")`.
- `async def cluster_stories(window_hours: int = 24) -> list[Story]`: assign unassigned, embedded sources
  in the window to stories (decision 0010). Returns stories created or updated (title, centroid).
  Idempotent; serialized by a Postgres advisory lock.
- `async def top_stories(limit=10, window_hours=24, min_sources=2) -> list[TopStory]` (`rank.py`):
  stories whose newest non-retracted source is in the window, with `min_sources`+ sources, ranked by
  distinct outlets, then source count, then recency. `TopStory`: id, title, n_sources, outlets, latest_at, sources[outlet, title, url, published_at].
- CLI (`app/cli.py`, script `newsroom`): `newsroom stories --top N [--hours 24] [--min-sources 2] [--refresh] [--json]`.
  `--refresh` runs ingest, then embed, then cluster first. Logs go to stderr, results to stdout.
- Planned: `async def search_live(query: str) -> list[Source]` (Tavily/Exa + Firecrawl, task 5.4).
- Every `Source` carries url, outlet, trust_score, published_at, content, content_hash.

## Invariants

- Never store the same `content_hash` twice. Never store the same normalized URL twice.
- `content_hash` = sha256 of lowercased, whitespace-collapsed `title + "\n" + content`.
- URLs are normalized: lowercase scheme and host, default port dropped, fragment dropped,
  tracking params (`utm_*`, fbclid, gclid, ...) removed.
- Fetched text is stored as plain text (HTML stripped, script/style dropped) and never interpreted as instructions.
- Every story has at least one source; stories with 2+ outlets are preferred by Producer.
- A source belongs to at most one story and is never reassigned. Retracted sources are never embedded or clustered.
- One feed failing never stops the others. A store failure fails the run.

## Current state

RSS ingest done (task 1.4): `parse.py` (feedparser, HTML to text, normalization, hash) and
`ingest.py` (concurrent httpx fetch, conditional GET by ETag/Last-Modified cached per process and
saved only after a successful store, in-run dedupe, Postgres insert). Spans: `reporter/ingest_feeds`
with a child `reporter/fetch_feed` per feed. Default feeds are 6 AI/tech outlets with a uniform
trust_score of 0.5 (placeholder). Live run on 2026-11-16: 91 sources from 6 outlets, a re-run
inserted 0. Content is the feed body only: often a summary of about 100 chars, and full text for
some outlets (capped at 20k chars). Clustering done (task 1.5) in `cluster.py`: pure `assign()`
plus DB functions. Spans are `reporter/embed_sources` and `reporter/cluster_stories`. Verified on
Postgres with a fake Voyage endpoint only, because there is no Voyage key yet. The 0.80 threshold
is uncalibrated. `top_stories` and the CLI are built (task 1.6). A live `newsroom stories --refresh`
ingested 91 sources but found 0 stories, because there is no Voyage key. Tests avoid `numpy.random` because Windows Application Control on the dev box
blocks its DLL.

## Open questions

- (none)

## Changelog

- 2026-11-16: node created from the design doc.
- 2026-11-16: empty package scaffolded (task 0.1).
- 2026-11-16: RSS ingest with url/content_hash dedupe, ARQ cron job (task 1.4).
- 2026-11-16: embed pending sources + greedy centroid clustering into stories (task 1.5, decision 0010).
- 2026-11-16: `top_stories()` ranking + `newsroom stories` CLI (task 1.6, acceptance pending Voyage key).
