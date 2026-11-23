---
id: press
type: component
status: in-progress
phase: 8
code: app/press/
depends_on: [reporter, writer, editor, standards-desk, producer, anchor, data-model, archive]
feeds: [web]
decisions: [0026, 0027, 0028, 0029]
---

# press

The Press feed: stories the crawlers (Reporter) gathered and clustered, with short paraphrased summaries for
readers to skim (not fact-checked), and telecasts: one story written, judged, cleared and voiced on request.

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
  Refresh (task 9.2): `stories.summary_sources` records the live sources a summary was written from; stories that
  gained `press_summary_refresh_growth` (2) more are rewritten after the new ones (`SummaryTodo.refresh`); a failed
  refresh keeps the old text and records the count so it waits for more growth. Pre-9.2 summaries count as 2.
- Runs from the worker's `ingest_job` after clustering (a missing chat key is logged and skipped) and from
  `newsroom summarize [--limit 10]`. Setting `press_summaries_per_run` (default 8, 0 = off).
- `PressStory.telecast: TelecastRef{id, step} | null`: the story's latest telecast (task 8.3).
- `POST /press/stories/{id}/telecast` -> 202 `TelecastView` (404 unknown story or < 2 live sources): reuses a ready
  telecast younger than `press_telecast_reuse_hours` (6) or a running one, else starts a job (`telecast.py`,
  decision 0027): `rundown_for_story` -> `draft_script` -> `review_script` -> `clear_for_air` -> `speak` to
  `media_dir/telecasts/<id>.wav` (then MP3, task 9.4), in the API process, `press_telecast_concurrency` (2) at a time.
- `GET /press/telecasts/{id}` -> `TelecastView{id, story_id, briefing_id, step (queued|writing|checking|clearing|
  voicing|ready|failed), error, created_at, updated_at, audio_url (/media/...), duration_ms, lines[id, text,
  start_ms, end_ms, words[text, start_ms, end_ms]] (voiced lines; words empty if the TTS gave none), verdicts
  {verdict: n}, story: PressStory}`. A running step not updated for
  `press_telecast_stale_minutes` (20) reads `failed` ("interrupted"). 404 unknown.
- `/media` (app/main.py): `StaticFiles(media_dir)` with HTTP Range. Settings `media_dir` (`var/media`),
  `press_telecast_seconds` (45).
- Retention (task 9.1, `media.py`): `cleanup_media(days=press_telecast_retention_days (7; 0 = keep), dry_run)` ->
  `MediaCleanup{expired, orphans, bytes_freed}`; older audio deleted, telecast `step='expired'`, `audio_path` NULL;
  unreferenced files over 1 h old deleted. Worker `cleanup_job` daily 03:15; CLI `newsroom cleanup-media`.
- Runner (task 9.3, `queue.py`): `dispatch()` per `press_telecast_runner` (auto|worker|inprocess); auto queues
  `telecast_job` (worker, timeout 900 s, one try) only if Redis answers and the worker health key is fresh
  (`WORKER_HEALTH_S` 15), else `schedule()` in-process. `start_telecast` holds `pg_advisory_xact_lock` per story
  around reuse-or-create.
- MP3 (task 9.4, `audio.py`): telecast audio is encoded to 64 kbps MP3 after voicing (WAV kept if encoding fails);
  `TelecastView.audio_lead_ms` = MP3 encoder+decoder delay (46 ms at 24 kHz, 0 for WAV). `newsroom
  transcode-media [--dry-run]` converts ready WAV telecasts.

## Invariants

- Summaries paraphrase (no 12-word copied runs, quotes under 15 words) and are labelled "not yet fact-checked" in the
  UI. Nothing from the Press feed is spoken: only telecasts, which go through the Editor and Standards Desk; a
  telecast voices only cleared lines and fails ("nothing ... verified well enough to air") if none clear.
- `run_telecast()` never raises: every failure ends `step=failed` with a reader-facing reason.
- Source text reaches the summary model only as escaped data in the user turn.
- Image URLs are stored, never fetched by the backend; the browser loads them, and only http(s) URLs are kept.

## Current state

Task 8.2 (decision 0026). Live 2026-11-23 on the dev DB: ingest backfilled thumbnails on 275 of 566 sources;
`newsroom summarize --limit 12` wrote 12 summaries (gpt-oss-20b, falling back to 120b on Groq 429s);
`/press/stories` returns them newest first with images and a working cursor. Integration tests
(`tests/integration/test_press_db.py`) cover order, paging, retracted sources, images, summaries and the backfill.
Telecast live 2026-11-23 (Cartesia voice, OpenRouter judge fallback): "Gemini 4 Neon" went writing -> checking
(76 s) -> voicing (10 s) -> ready in 90 s: 10 lines, 45.3 s of audio, 10/10 claims approved; `/media` served it
with Range through the web proxy. Job unit tests fake the pipeline; DB tests cover reuse, stale rows and the view.

## Open questions

- (none)

## Changelog

- 2026-11-23: node created; Press feed API, RSS thumbnails, crawler summaries (task 8.2, decision 0026).
- 2026-11-23: telecasts: `POST /press/stories/{id}/telecast`, `GET /press/telecasts/{id}`, `/media` (task 8.3, decision 0027).
- 2026-11-23: `TelecastLine.words` from `script_lines.audio_words` (task 8.4).
- 2026-11-23: telecast audio retention: `cleanup_media`, daily worker job, `newsroom cleanup-media`, `expired` step (task 9.1, decision 0029).
- 2026-11-23: summaries refreshed when a story gains 2+ live sources (task 9.2).
- 2026-11-23: telecasts run on the ARQ worker when one is alive, else in-process; per-story start lock (task 9.3).
- 2026-11-23: MP3 telecast audio, `audio_lead_ms`, `newsroom transcode-media` (task 9.4).
