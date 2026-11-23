# Newsroom frontend: Press feed + on-demand animated TV telecast

Status: approved 2026-11-23, including the backend changes in section 3. I build in phases and stop after
each one for your review: one PR per phase, and I never merge.

## 1. Context
Newsroom works like a news press:
- **Press (short view):** the stories our crawlers (the Reporter) gathered and clustered. Each one is readable as a
  short card.
- **Telecast:** when a reader likes a story, they can broadcast it. This runs the full pipeline on that one story:
  Writer, Editor judge, Standards Desk, then Anchor voice. It plays as an animated TV segment, and it lands in the
  existing **News Archive** with its claims, verdicts and sources.

The archive pages (`/briefings`, `/rejections`) stay as they are.

## 2. What the backend has today (findings)

### Routes
The OpenAPI spec is in `web/openapi.json`, and the app is in `app/main.py`.

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/health` | `Health{status, version, env}` |
| GET | `/archive/briefings?limit` | `BriefingSummary[]`: id, created_at, status, target_minutes, lines, verdicts, corrections, wall_ms, tokens, cost |
| GET | `/archive/briefings/{id}` | `BriefingDetail{briefing, lines: LineSummary[id, order, kind, text, story_title, verdicts, question], stages, corrections}` |
| GET | `/archive/lines/{id}/trace` | `ClaimTrace`: the line, `audio_start_ms`/`audio_end_ms`, claims with cited `SourceRef{outlet, title, url, published_at, retracted}`, evidence, judge history including conflicts |
| GET | `/archive/rejections`, `/archive/corrections` | rejection log, corrections |
| WS | `/anchor/briefings/{id}/live` | live PCM16 mono stream plus JSON events (`start`, `line{line_id, text, start_ms}`, `line_end{end_ms}`, `paused`, `resumed`, `done`, caller events). Push-to-talk questions go over the same socket. |

- **No CORS middleware.** The current web app fetches from the server side.

### Audio
- Audio exists only as the live WebSocket stream above. Cartesia synthesizes it again on every play.
- Timing is **line-level only**: `start_ms`/`end_ms` per line, also stored as `script_lines.audio_start_ms/end_ms`.
- There are **no word or phoneme timestamps and no visemes**.
- `newsroom speak` can write a WAV file, but nothing serves it.

### Story fields
- **Story:** `id`, `title`, `summary` (a column exists but **is never filled**), `created_at`.
- **Source:** `outlet`, `title`, `url`, `published_at`, `content` (crawled text), `trust_score`, `retracted`.
- `top_stories()` (`app/reporter/rank.py`) adds `n_sources`, `outlets`, `latest_at`, and the sources.
- **There is no image, no category and no location field.** All 16 feeds are AI/tech, so the category bar is
  hidden for now (your choice).
- Script lines carry `story_id`, `text`, `kind` (`script`/`answer`/`correction`) and timings. Only lines the
  Standards Desk cleared ever air.

## 3. Proposed backend changes (approved together with this plan)

Each change is small, tested and documented in context nodes. Decision 0026 records the Press/Telecast design.

### B1: feed (Phase 2)
- **Images.** The ingest parses RSS `media:thumbnail`, `media:content` and image enclosures into a new
  `sources.image_url` column (Alembic migration). A story's image is that of its newest source with one.
  - The image is a hotlinked publisher thumbnail, credited with the outlet's name. Otherwise the card falls back to
    a gradient.
- **Short summaries.**
  - A new Writer function, `summarize_story()`, writes a paraphrase of about 60 words from the story's sources.
  - It goes through the LLM gateway, with sources in the user turn as escaped data (never in the system prompt).
  - It is checked against the Standards Desk's copied-words limit (12 words), since summaries paraphrase and never
    copy.
  - The worker fills `Story.summary` after clustering, for the top N stories per run, capped to save quota.
  - The UI labels it "Press summary from N outlets · not yet fact-checked". The fact-checked version is the
    telecast.
- **`GET /press/stories?limit&before`:**
  - returns `PressStory{id, title, summary, image_url, outlets, n_sources, latest_at, sources[outlet, title, url,
    published_at], telecast: {id, status} | null}`
  - newest first, cursor-paged, only stories with 2 or more sources (as today)

### B2: telecast (Phase 3)
- **`POST /press/stories/{id}/telecast`** creates (or reuses, if a ready one is under 6 h old) a one-story
  briefing. It runs as a background task in the API process (at most 2 at once):
  - rundown for that story
  - `draft_script`
  - `review_script` (judge and rewrite loop, now with the OpenRouter fallback)
  - `clear_for_air`
  - render the cleared lines to an audio file once
- **`GET /press/telecasts/{id}`** returns the status (`writing`, `checking`, `clearing`, `voicing`, `ready`,
  `failed` with a reason). When ready it also returns:
  - `{audio_url, duration_ms, lines[{id, text, start_ms, end_ms, words?[{text, start_ms, end_ms}]}], story,
    sources, verdict counts}`
- **New table `telecasts`:** story_id, briefing_id, step, error, audio_path, duration_ms, timestamps.
  - Audio goes in `NEWSROOM_MEDIA_DIR` (default `var/media/`, gitignored), served at `/media` with HTTP Range
    support.
  - The format is WAV PCM16, about 3 MB per minute; MP3 is out of scope.
- **Word timings.** Cartesia can return word timestamps. Phase 4 starts with a short spike to request them in
  `app/anchor/tts.py`. If they aren't available through our Pipecat adapter, words get estimated timings, spread
  over each line's measured duration in proportion to word length, and are marked `estimated`.
- **Nothing cleared.** If no line clears, the telecast ends `failed` ("couldn't verify this story enough to air
  it"), with a link to its Archive trace. Nothing unapproved is ever voiced.
- **No CORS change.** Next.js rewrites proxy `/api/*` and `/media/*` to the backend, so the browser sees one
  origin. That also lets the Web Audio AnalyserNode read the audio.

## 4. Frontend design (inside `web/`, Next.js 16, your choice)

### Why Next.js
- It reuses the generated API types (`npm run gen:api`), the CI `web` job and the dev server.
- The same-origin proxy removes the need for CORS.
- Feed and broadcast are client components (`"use client"`), so they behave like a Vite single-page app inside it.

### Stack
- Tailwind CSS v4
- **Framer Motion** for the feed and UI transitions
- **GSAP** for the broadcast. A single `gsap.timeline()` is paused and its time is set from the audio clock on every
  frame (`tl.seek(clock.ms/1000)`), so pause, speed, replay and scrubbing move every animation together. Framer
  Motion's per-component springs can't be scrubbed as one timeline.
  - *Update (task 8.4, decision 0028):* GSAP was not needed. `ShowClock` already drives every component
    from one time value, and the anchor's pose and mouth are pure functions of show time.
- TanStack Query and Zustand
- Fonts: Oswald and Inter via `next/font`
- **Vitest** replaces `node --test`; the 3 existing lib tests move over.

### Routes
- `/`: Press feed (the archive list moves to `/archive`, with links updated)
- `/watch/[storyId]`: Telecast (Esc goes back to the feed)

### Layout
Everything lives under `web/src/`:
```
api/        client.ts (typed with lib/api-types), press.ts (queries/mutations)
features/feed/       FeedPager, StoryCard, CategoryBar (hidden until categories exist), CardSkeleton
features/broadcast/  BroadcastPlayer, Preparing (pipeline progress), Bumper, StudioScene, Anchor/ (layered SVG:
                     head, eyes, brows, mouth shapes, torso), OtsBox, BRoll, LowerThird, Ticker, Captions,
                     LiveBug, Outro, Controls
broadcast/  buildBroadcastScript(telecast, feed) -> BroadcastScript{segments: bumper, intro, body, broll, outro;
            cues: lowerThirds, captions, emphasis, nod}. It's pure, so all timings live in one place.
audio/      useAudioClock (HTMLAudioElement + rAF: the single source of time), useAmplitude (AnalyserNode),
            useWordSync / mouth-shape mapping, preload
store/      player store (playing, rate, muted, captions, current telecast, queue)
```

### Behaviour
- **Feed:** full-screen vertical pager with wheel, arrow keys and touch swipe, and snap transitions. Each card shows:
  - the image or a gradient
  - the headline
  - the summary
  - the outlets and time
  - a "Watch Broadcast" button
  - after a telecast, a "Fact-checked" badge
- **Telecast:** the button calls `POST telecast` and opens `/watch/[id]`.
  - **Preparing screen:** an animated "Going to air…" with the real pipeline steps (writing → fact-checking →
    clearing → voicing).
  - Then the bumper, with BREAKING when the newest source is under 3 hours old and 3 or more outlets cover it;
    otherwise TOP STORY.
  - **Studio:** a desk, an animated anchor (blinks, breathing, head tilts, a look-up at the start, a nod at the end),
    then the over-the-shoulder box and a B-roll Ken Burns shot partway through.
  - **Graphics:** a lower third with the headline and source, and a second lower third with "Fact-checked: x of y
    claims approved · N outlets" (there is no location field). A ticker shows the other feed headlines; the LIVE bug
    shows a clock.
  - **Captions** are word-level when timings exist, otherwise line-level.
  - **Outro:** a "Next story" countdown of 5 s that can be cancelled.
- **Controls:** play/pause, replay, mute, captions, speed (0.75 to 1.5), prev/next, Esc.
- **Lip sync:** visemes or words drive the mouth shapes when available, otherwise AnalyserNode amplitude.
- **Preloading:** the next story's audio and image load while the current one plays, if its telecast is ready.
- **Errors:**
  - backend down: a retry state
  - telecast failed: reason plus Archive link
  - audio failed: captions-only playback on a timer clock
  - missing image: a gradient
- **Motion and accessibility:**
  - with `prefers-reduced-motion`, audio and captions stay; the anchor gets a static pose and fades replace motion
  - only transform and opacity are animated
  - ARIA labels, keyboard support, and captions on by default
- **Responsive:** on a portrait phone the feed is primary and the broadcast is letterboxed 16:9; on desktop it fills
  the screen.
- **Config:** `NEWSROOM_API_URL` already exists. `.env.example` in `web/` documents it.

## 5. Phases (each ends with a PR and a stop for your review)
1. **Plan:** `FRONTEND_PLAN.md` (this file). Done.
2. **B1 plus feed:** the image migration and ingest, `summarize_story` plus the worker hook, `GET /press/stories`,
   OpenAPI and `gen:api`. Then Tailwind, Vitest, the API client, FeedPager and StoryCard, skeletons, and moving the
   archive to `/archive`.
3. **B2 plus player skeleton:** the telecast table, routes, background job and file render, `/media`, and the Next
   rewrites. Then `buildBroadcastScript`, `useAudioClock`, controls, captions, the Preparing screen and a plain
   stage.
4. **Studio, anchor and lip sync:** the Cartesia word-timestamp spike, then the layered SVG anchor, idle life, and
   viseme/amplitude mouth.
5. **Polish:** bumper, lower thirds, ticker, LIVE bug, B-roll, outro and auto-advance.
6. **Hardening:** responsive layout, reduced motion, error states, tests, and the README section on running frontend
   and backend together.

## 6. Tests and verification
- **Backend:** pytest for:
  - RSS image extraction
  - the summary copy check and prompt isolation
  - `/press/stories` paging
  - telecast state machine: success, nothing cleared, TTS missing (using the fake TTS)
  - Range on `/media`
  - Plus the existing suite, ruff, mypy, and `context_graph check`.
- **Frontend:** Vitest for:
  - `buildBroadcastScript` (segment boundaries, cue ordering, missing image or words)
  - `useAudioClock` (pause, rate, seek; fake-timer and fake-audio harness)
  - word sync and mouth mapping
  - the BREAKING rule
  - Plus `tsc --noEmit` (strict, no `any`) and `next build`.
- **End to end, each phase:** run the API on :8001 and the web app on :3001.
  - Scroll the feed and telecast a real story (Cartesia key needed for voice; `NEWSROOM_ANCHOR_TTS=fake` for a
    silent run).
  - Check pause and seek stay in sync, and check the result in `/archive`.
  - Take screenshots with headless Chrome.

## 7. Notes and risks
- **Cost and wait.** A telecast takes about 1 to 3 minutes and uses LLM calls plus one TTS render. The Preparing
  screen shows the real progress, and a ready telecast is reused.
- **Images.** These are hotlinked publisher thumbnails from RSS, credited with the outlet's name. If you'd rather not
  hotlink, gradients only.
- **Original artwork.** The anchor character and channel branding ("NEWSROOM") are original. They don't imitate any
  real network.
- **Not in scope yet:** push-to-talk questions during a telecast (the live WebSocket keeps them for full briefings),
  categories and MP3.
