---
id: data-model
type: shared
status: planned
phase: 1
code: app/db/
depends_on: []
feeds: [reporter, writer, editor, archive]
decisions: [0001]
---

# data-model

Postgres schema and migrations. Holds the trace chain from source to spoken audio.

## Contract

- Tables: sources, stories, story_sources, briefings, script_lines, claims, claim_evidence, traces.
- Chain: sources -> stories -> script_lines -> claims -> claim_evidence.
- Embedding model and dimension: (fill in when chosen).

## Invariants

- Every schema change ships with an Alembic migration.
- Applied migrations are never edited.

## Current state

Empty package scaffolded at `app/db/` (docstring only, no public surface yet). Logic not started. Planned for phase 1.

## Open questions

- (none)

## Changelog

- 2026-11-16: node created from the design doc.
- 2026-11-16: empty package scaffolded (task 0.1).
