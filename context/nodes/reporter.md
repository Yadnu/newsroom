---
id: reporter
type: component
status: in-progress
phase: 1
code: app/reporter/
depends_on: [data-model, llm-gateway, archive, standards-desk]
feeds: [producer, press]
decisions: [0003, 0010, 0021, 0023, 0026]
---

# reporter

Fetches news from the internet, dedupes it, and clusters sources into stories.

## Contract

- `async def ingest_feeds(feeds: Sequence[FeedConfig] | None = None, *, transport=None, store=insert_new_sources) -> IngestReport`:
  pull the configured RSS/Atom feeds (`Settings.reporter_feeds`) and store new `sources`.
  `IngestReport`: feeds_total, feeds_failed, feeds_not_modified, entries_seen, new_sources,
  duplicates, errors (feed url -> reason).
- `async def insert_new_sources(rows: Sequence[NewSource]) -> int`: `INSERT ... ON CONFLICT DO NOTHING`
  against the unique `url` and `content_hash`. Returns the number of rows inserted. Then sets `image_url` on
  existing rows that had none (task 8.2).
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
  distinct outlets, then source count, then recency. `TopStory`: id, title, n_sources, outlets, latest_at, sources[`StorySourceRef`: id, outlet, title, url, published_at].
- CLI (`app/cli.py`, script `newsroom`): `newsroom stories --top N [--hours 24] [--min-sources 2] [--refresh] [--json]`.
  `--refresh` runs ingest, then embed, then cluster first. Logs go to stderr, results to stdout.
- `async def search_live(query, *, max_results=None, days=None, settings=None, transport=None, store=..., lookup=...)
  -> list[LiveSource(id, url, outlet, title, published_at)]` (`search.py`, task 5.4, decision 0021): Tavily news
  search (`topic=news`, `reporter_search_days` 7, `reporter_search_max_results` 5, `include_raw_content`); results
  whose text is under `reporter_search_min_chars` (1200) are fetched with Firecrawl `/v1/scrape` (markdown, main
  content). Stored through `insert_new_sources` (url and content_hash dedupe, normalised URL, outlet from the
  domain, `reporter_search_trust` 0.5, capped at `reporter_fetch_max_chars`); known URLs are reused without a
  fetch; identical queries cached `reporter_search_cache_s` (600). Fails soft: no key or a provider error -> `[]`.
  Spans `reporter/search_live` > `reporter/fetch_page`. CLI `newsroom search "query" [--days N]`.
- Every `Source` carries url, outlet, trust_score, published_at, content, content_hash.
- `async def retract_source(ref: UUID | str, reason) -> RetractionReport(source_id, url, outlet, reason, already,
  briefings: tuple[Flagged], on_air)` (`retract.py`) (task 6.2, decision 0023): by id or URL (normalised); sets `retracted`,
  `retracted_at`, `retraction_reason` and runs `standards_desk.flag_retraction` in the same transaction.
  Idempotent; `SourceNotFoundError`. `async def recheck_sources(hours=reporter_recheck_hours 48, *, transport,
  sources) -> RecheckReport(checked, unreachable, retracted)`: GETs live sources behind briefings of the last
  `hours` (max `reporter_recheck_max` 200); retracts only on HTTP 404/410 or `RETRACTION_PATTERNS` (publisher
  notices), see `retraction_signal(status, body)`. Spans `reporter/retract_source`, `reporter/recheck_sources` >
  `recheck_page`. CLI `newsroom retract <id|url> --reason`, `newsroom recheck [--hours]`.
- Scheduled recheck (task 7.2): `app/worker.py` `recheck_job` runs `recheck_sources()` every
  `reporter_recheck_every_hours` (default 6, 0 = off) at minute 30, unique, not at startup. New retractions are
  logged as `worker.sources_retracted`; the next `newsroom brief` airs their corrections (decision 0023).

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
with a child `reporter/fetch_feed` per feed. Default feeds: 16 feeds from 15 AI/tech outlets (10 added 2026-11-18, all
returned 200; VentureBeat 429 and Semafor 404 left out), uniform trust_score 0.5 (placeholder). Live run on 2026-11-16: 91 sources from 6 outlets, a re-run
inserted 0. Content is the feed body only: often a summary of about 100 chars, and full text for
some outlets (capped at 20k chars). Clustering done (task 1.5) in `cluster.py`: pure `assign()`
plus DB functions. Spans are `reporter/embed_sources` and `reporter/cluster_stories`. The 0.80 threshold
is uncalibrated. `top_stories` and the CLI are built (task 1.6). Live `newsroom stories --refresh`
(2026-11-18, 7 min with Voyage free-tier pacing): 263 new sources embedded, top 10 all with 2+ sources and up to
4 outlets (task 1.6 acceptance). Two top stories look like one event (Anthropic IPO) split in two clusters. Tests avoid `numpy.random` because Windows Application Control on the dev box
blocks its DLL.

## Open questions

- (none)

## Changelog

- 2026-11-16: node created from the design doc.
- 2026-11-16: empty package scaffolded (task 0.1).
- 2026-11-16: RSS ingest with url/content_hash dedupe, ARQ cron job (task 1.4).
- 2026-11-16: embed pending sources + greedy centroid clustering into stories (task 1.5, decision 0010).
- 2026-11-16: `top_stories()` ranking + `newsroom stories` CLI (task 1.6, acceptance pending Voyage key).
- 2026-11-17: `StorySourceRef` gains the source `id` (needed by the Writer, task 2.1).
- 2026-11-18: 10 more default feeds; task 1.6 acceptance met on a live run.
- 2026-11-19: `search_live()` with Tavily + Firecrawl for on-air answers (task 5.4).
- 2026-11-21: `retract_source()` and `recheck_sources()` (task 6.2, decision 0023).
- 2026-11-23: ARQ `recheck_job` every 6 h runs the retraction recheck (task 7.2).
- 2026-11-23: feed thumbnails parsed (`FeedEntry.image_url`, `entry_image()`) and stored as `sources.image_url`; ingest backfills missing ones (task 8.2).
