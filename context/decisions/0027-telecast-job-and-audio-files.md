---
id: "0027"
title: Telecasts run the full briefing path on one story in the API process and render audio once to a file
status: accepted
date: 2026-11-23
nodes: [press, producer, data-model, web]
---

# 0027: Telecasts run the full briefing path on one story in the API process and render audio once to a file

## Context
Task 8.3 (FRONTEND_PLAN.md B2). A reader picks a Press story and watches it as a TV segment with replay, speed,
seeking and synced captions. The only audio path was the live WebSocket stream, synthesized again on every play,
with no seeking. Everything spoken must be approved and cleared.

## Decision
- `POST /press/stories/{id}/telecast` creates a `telecasts` row and runs a background job in the API process
  (`press_telecast_concurrency`, default 2): `rundown_for_story` (its own one-story briefing, not limited to fresh
  stories) -> `draft_script` -> `review_script` -> `clear_for_air` -> `speak` into a WAV file under `media_dir`.
  Each step is written to the row; `GET /press/telecasts/{id}` returns progress and, when `ready`, the audio URL,
  line timings, verdict counts and the story.
- A ready telecast of the story younger than `press_telecast_reuse_hours` (6) is reused, as is one still running;
  a row stuck in a running step for `press_telecast_stale_minutes` (20) reads as failed ("interrupted").
- Audio is served at `/media` by Starlette `StaticFiles` (HTTP Range for seeking); the web app proxies `/media`
  and `/api` on the same origin. WAV (PCM16 mono), about 3 MB per minute.
- Failures end the job with a reader-facing reason (nothing cleared, TTS not configured, LLM unavailable, ...),
  never an exception; unexpected errors are logged and read "internal error".

## Alternatives considered
- ARQ worker job: survives API restarts, but needs Redis and the worker running for every telecast; the in-process
  job is enough for one-off reader requests, and stale rows are detected.
- Reuse the live WebSocket stream: no seek, replay or speed, and a TTS render on every play.
- MP3: smaller, but needs an encoder dependency; deferred.

## Consequences
A telecast takes about 1 to 2 minutes (most of it the Editor). Jobs die with the API process (the row then reads
failed after 20 minutes). Audio files accumulate under `var/media/` (gitignored) with no cleanup yet.
