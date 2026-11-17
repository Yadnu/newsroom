---
id: web
type: app
status: planned
phase: 4
code: web/
depends_on: [anchor, archive]
feeds: []
decisions: []
---

# web

Next.js player and Archive dashboard.

## Contract

- Player: audio, synced transcript, click a sentence to open its claim trace.
- Archive: briefing timeline, rejection log, latency per stage, cost per briefing.

## Invariants

- Talks only to the FastAPI backend.
- API types generated from OpenAPI.

## Current state

Not started. Planned for phase 4.

## Open questions

- (none)

## Changelog

- 2026-11-16: node created from the design doc.
