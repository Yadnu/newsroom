---
id: producer
type: component
status: planned
phase: 2
code: app/producer/
depends_on: [reporter, caller, standards-desk, archive]
feeds: [writer, anchor]
decisions: []
---

# producer

Orchestrates the show: picks stories, orders the rundown, budgets time, and routes Caller questions.

## Contract

- `async def build_rundown(minutes: int, topics: list[str] | None) -> Rundown`
- `async def handle_call(question: CallerQuestion) -> CallerAnswerPlan`: pause, run a fast Reporter -> Writer -> Editor loop, resume.
- Rundown items: story_id, order, target_seconds.

## Invariants

- Only stories inside the freshness window enter a rundown.
- A Caller answer has its own latency budget and falls back to "I'll check on that" if it overruns.

## Current state

Empty package scaffolded at `app/producer/` (docstring only, no public surface yet). Logic not started. Planned for phase 2 (simple rundown), expanded in phase 5 (caller routing).

## Open questions

- (none)

## Changelog

- 2026-11-16: node created from the design doc.
- 2026-11-16: empty package scaffolded (task 0.1).
