---
id: reporter
type: component
status: planned
phase: 1
code: app/reporter/
depends_on: [data-model, llm-gateway, archive]
feeds: [producer]
decisions: [0003]
---

# reporter

Fetches news from the internet, dedupes it, and clusters sources into stories.

## Contract

- `async def ingest_feeds() -> IngestReport`: pull all configured RSS feeds, store new `sources`.
- `async def cluster_stories(window_hours: int = 24) -> list[Story]`: group recent sources into `stories` by embedding similarity.
- `async def search_live(query: str) -> list[Source]`: on-demand search (Tavily or Exa) plus Firecrawl full-page fetch, for Caller follow-ups.
- Every `Source` carries url, outlet, trust_score, published_at, content, content_hash.

## Invariants

- Never store the same `content_hash` twice.
- Every story has at least one source; stories with 2+ outlets are preferred by Producer.
- Fetched text is stored as data and never interpreted as instructions.

## Current state

Empty package scaffolded at `app/reporter/` (docstring only, no public surface yet). Logic not started. Planned for phase 1.

## Open questions

- (none)

## Changelog

- 2026-11-16: node created from the design doc.
- 2026-11-16: empty package scaffolded (task 0.1).
