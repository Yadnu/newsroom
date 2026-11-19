---
id: web
type: app
status: in-progress
phase: 3
code: web/
depends_on: [anchor, archive]
feeds: []
decisions: []
---

# web

Next.js player and Archive dashboard.

## Contract

- Player (task 4.3, not built): audio, synced transcript, click a sentence to open its claim trace. It will consume
  the Anchor's WebSocket `/anchor/briefings/{id}/live` (PCM16 + JSON line events, decision 0017).
- Archive dashboard (task 3.3): `/` briefing list (verdict counts, wall time, tokens, cost);
  `/briefings/[id]?line=<line_id>` script with per-line verdict dots, the selected line's claim trace (verdicts,
  cited source links, evidence passages, earlier verdicts), stage table, and the briefing's rejections;
  `/rejections[?only=rejected]` global rejection log linking to each sentence.
- Config: `NEWSROOM_API_URL` (default `http://localhost:8000`), read server-side only.

## Invariants

- Talks only to the FastAPI backend, from server components (`lib/api.ts` is `server-only`).
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

## Open questions

- (none)

## Changelog

- 2026-11-16: node created from the design doc.
- 2026-11-19: Archive dashboard scaffolded and built (task 3.3).
