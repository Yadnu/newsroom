---
id: press
type: component
status: in-progress
phase: 8
code: app/press/
depends_on: [reporter, writer, standards-desk, data-model, archive]
feeds: [web]
decisions: [0026]
---

# press

The Press feed: stories the crawlers (Reporter) gathered and clustered, with short paraphrased summaries for
readers to skim. Not fact-checked; the telecast (task 8.3) is.

## Contract

- `GET /press/stories?limit=20&after_latest_at=&after_id=` -> `PressPage{stories: PressStory[], next: PressCursor | null}`.
  Newest first (newest live source's `published_at`, else `fetched_at`), keyset-paged on `(latest_at, id)`; `limit`
  1..50; the two cursor params go together (422 otherwise). A short page has `next = null`.
- `PressStory{id, title, summary | null, image_url | null, image_outlet | null, outlets, n_sources, latest_at,
  sources: PressSource[id, outlet, title, url, published_at] (newest first, max 8)}`. Only stories with 2+ live
  (non-retracted) sources. Image = the newest source with a feed thumbnail, credited to its outlet.
- `async def press_stories(limit, after: PressCursor | None, min_sources=2) -> list[PressStory]` (`feed.py`).
- `async def fill_summaries(limit=press_summaries_per_run) -> int` (`summaries.py`): summaries for the newest stories
  without one. Each comes from `writer.summarize_story()` and must pass `standards_desk.clear.copied_run()`
  (`standards_max_copied_words`, 12) against the story's sources; a copying summary is retried once with that
  feedback, then skipped. `WriterError` and `LLMError` skip the story; `LLMConfigError` is raised.
- Runs from the worker's `ingest_job` after clustering (a missing chat key is logged and skipped) and from
  `newsroom summarize [--limit 10]`. Setting `press_summaries_per_run` (default 8, 0 = off).

## Invariants

- Summaries paraphrase (no 12-word copied runs, quotes under 15 words) and are labelled "not yet fact-checked" in the
  UI. Nothing from the Press feed is spoken: only telecasts, which go through the Editor and Standards Desk.
- Source text reaches the summary model only as escaped data in the user turn.
- Image URLs are stored, never fetched by the backend; the browser loads them, and only http(s) URLs are kept.

## Current state

Task 8.2 (decision 0026). Live 2026-11-23 on the dev DB: ingest backfilled thumbnails on 275 of 566 sources;
`newsroom summarize --limit 12` wrote 12 summaries (gpt-oss-20b, falling back to 120b on Groq 429s);
`/press/stories` returns them newest first with images and a working cursor. Integration tests
(`tests/integration/test_press_db.py`) cover order, paging, retracted sources, images, summaries and the backfill.
A summary is written once; it is not refreshed when a story gains sources.

## Open questions

- (none)

## Changelog

- 2026-11-23: node created; Press feed API, RSS thumbnails, crawler summaries (task 8.2, decision 0026).
