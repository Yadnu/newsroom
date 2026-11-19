---
id: web
type: app
status: in-progress
phase: 4
code: web/
depends_on: [anchor, archive]
feeds: []
decisions: []
---

# web

Next.js player and Archive dashboard.

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
- `NEWSROOM_PUBLIC_API_URL`: the API as the browser reaches it (WebSocket base); defaults to `NEWSROOM_API_URL`.
- Archive dashboard (task 3.3): `/` briefing list (verdict counts, wall time, tokens, cost);
  `/briefings/[id]?line=<line_id>` script with per-line verdict dots, the selected line's claim trace (verdicts,
  cited source links, evidence passages, earlier verdicts), stage table, and the briefing's rejections;
  `/rejections[?only=rejected]` global rejection log linking to each sentence.
- Config: `NEWSROOM_API_URL` (default `http://localhost:8000`), read server-side only.

## Invariants

- Talks only to the FastAPI backend: server components for data (`lib/api.ts` is `server-only`); the browser
  opens only the Anchor WebSocket.
- API types generated from OpenAPI: `scripts/export_openapi.py` writes `web/openapi.json`, `npm run gen:api`
  writes `lib/api-types.ts`. CI fails if either is stale.
- Links built from feed data go through `safeHref()` (http/https only).

## Current state

Next.js 16.4 (App Router, Cache Components, React 19.3) in `web/`, no CSS framework, system fonts.
Every API read awaits `connection()` inside a `<Suspense>` boundary, so pages prerender a shell and stream data at
request time; the build never calls the API. Commands: `npm run dev|build|lint|typecheck|test`
(`typecheck` runs `next typegen` first; tests are `node --test` on pure helpers). CI job `web` runs them all.
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
