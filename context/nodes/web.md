---
id: web
type: app
status: in-progress
phase: 4
code: web/
depends_on: [anchor, archive, press]
feeds: []
decisions: [0026, 0027, 0028]
---

# web

Next.js app: the Press feed, the Player, and the Archive dashboard.

## Contract

- Player (task 4.3): `/briefings/[id]/listen[?line=<line_id>]`. Play opens the Anchor WebSocket
  `/anchor/briefings/{id}/live` from the browser (decision 0017), schedules the PCM16 chunks with Web Audio,
  highlights the sentence being heard (audio-clock mapping in `lib/player.ts`), pauses/resumes over the socket,
  greys lines that never aired (held back by the Standards Desk), and a click opens that line's claim trace.
  Linked from the briefing page and from cleared/aired briefings in the list.
- Push-to-talk (task 5.1): "Hold to ask" pauses the Anchor, captures the mic (AudioWorklet
  `public/mic-worklet.js`, `lib/mic.ts` downsamples to 16 kHz PCM16), sends `mic_start` / chunks / `mic_end`, and
  shows live interim words and the classified question (intent badge, story). Resume continues the briefing.
  A question the Standards Desk blocked shows "not taken: <category>" with the reason (task 5.2).
  Answers (task 5.3): the card shows "Checking sources...", then the answer lines, highlighted while spoken;
  playback resumes by itself. The briefing page labels answer lines "Answer to: <question>".
- `NEWSROOM_PUBLIC_API_URL`: the API as the browser reaches it (WebSocket base); defaults to `NEWSROOM_API_URL`.
- Press feed (task 8.2): `/` full-screen vertical pager of `/press/stories` (wheel, arrow/PageUp/PageDown/j/k/space
  keys, touch swipe, prev/next buttons; next page prefetched 3 cards before the end). Card: feed thumbnail credited
  to its outlet or a stable gradient, outlets + time ago, headline, crawler summary labelled "not yet fact-checked",
  up to 3 source links, "Watch broadcast" (links to the telecast; "Fact-checked broadcast ready" when one is). Loading skeleton, offline state with retry, empty
  state. Code in `src/` (`api/client.ts` typed fetch via `/api`, `api/press.ts` TanStack infinite query,
  `features/feed/`). Route groups: `app/(press)` (no header, `data-press` reset) and `app/(archive)`.
- Telecast player (task 8.3): `/watch/[storyId]` starts or reuses the story's telecast (`useTelecast`: POST, then
  polls every 2 s), shows the real steps ("Going to air"), then plays it. `src/broadcast/script.ts`
  `buildBroadcastScript()` is the single timeline (bumper 2.5 s, intro, body = audio, b-roll on a caption boundary
  near 40%, outro 5 s; captions, lower thirds, BREAKING if newest source < 3 h and 3+ outlets);
  `src/broadcast/clock.ts` `ShowClock` is the only clock (audio element is master during speech, wall clock
  otherwise and for captions-only). Controls: play/pause, replay, seek bar, prev/next story, mute, captions (on by
  default), speed 0.75-1.5, exit; keys space/k, m, c, r, arrows, n/p, Esc.
  Studio (task 8.4, decision 0028): `StudioScene` (skyline, light sweep, desk) and `Anchor` (original layered SVG).
  `poseAt()` (blinks, breathing, tilts, papers, nod, brows) and `mouthAt()` (letter visemes from word timings;
  `useAmplitude` scales them only for estimated words) are pure functions of show time; captions highlight the
  current word. Reduced motion: still pose, mouth and captions only. No GSAP.
  Failed telecast: reason, retry, link to the briefing in the Archive.
- Archive dashboard (task 3.3): `/archive` briefing list (verdict counts, wall time, tokens, cost);
  `/briefings/[id]?line=<line_id>` script with per-line verdict dots, the selected line's claim trace (verdicts,
  cited source links, evidence passages, earlier verdicts), stage table, and the briefing's rejections;
  `/rejections[?only=rejected]` global rejection log linking to each sentence.
- Config: `NEWSROOM_API_URL` (default `http://localhost:8000`), read server-side only.

## Invariants

- Talks only to the FastAPI backend: Archive pages read through server components (`lib/api.ts` is `server-only`);
  the browser calls the API only through the same-origin `/api/*` and `/media/*` rewrites (`next.config.ts`, to
  `NEWSROOM_API_URL`) and opens the Anchor WebSocket.
- API types generated from OpenAPI: `scripts/export_openapi.py` writes `web/openapi.json`, `npm run gen:api`
  writes `lib/api-types.ts`. CI fails if either is stale.
- Links built from feed data go through `safeHref()` (http/https only).

## Current state

Next.js 16.4 (App Router, Cache Components, React 19.3) in `web/`. Archive: plain CSS (`app/archive.css`, imported
into Tailwind's `base` layer, no preflight). Press: Tailwind v4 utilities, Framer Motion (`MotionConfig
reducedMotion="user"`), TanStack Query, Oswald/Inter via `next/font`. Tests are Vitest (`npm test`).
Every API read awaits `connection()` inside a `<Suspense>` boundary, so pages prerender a shell and stream data at
request time; the build never calls the API. Commands: `npm run dev|build|lint|typecheck|test`
(`typecheck` runs `next typegen` first). CI job `web` runs them all.
Verified live (2026-11-19) against the dev DB: one click on a sentence of briefing `3873a08c` shows its
TechCrunch source link. Older rejections have no `line_id`, so the log shows them unlinked.
Player (task 4.3): `components/Player.tsx` (client) + pure `lib/player.ts` (PCM decode, `AudioClock`, `activeLine`,
`applyEvent`; `node --test`). Live check 2026-11-19 against Cartesia on `3873a08c` with a Node client running the
same logic: 5 lines highlighted in order, pause at 4 s and resume, 31.8 s of audio. In-browser listening was not
automated (no browser in the agent environment).

## Open questions

- (none)

## Changelog

- 2026-11-16: node created from the design doc.
- 2026-11-19: Archive dashboard scaffolded and built (task 3.3).
- 2026-11-19: live Player with synced, clickable transcript (task 4.3).
- 2026-11-19: push-to-talk questions in the Player (task 5.1).
- 2026-11-19: answer card in the Player, answer lines labelled on the briefing page (task 5.3).
- 2026-11-21: briefing page Corrections banner and `Correction` line badge; corrections badge on the list (task 6.2).
- 2026-11-21: trace panel shows "Sources disagree" conflicts under a judgement (task 6.3).
- 2026-11-23: Press feed at `/` (Tailwind, Framer Motion, TanStack Query); Archive moved to `/archive`; Vitest (task 8.2).
- 2026-11-23: telecast player skeleton at `/watch/[storyId]`: timeline, ShowClock, controls, captions (task 8.3).
- 2026-11-23: studio scene, animated anchor, word-timed lip sync and captions (task 8.4).
