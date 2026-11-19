---
id: producer
type: component
status: in-progress
phase: 2
code: app/producer/
depends_on: [reporter, caller, standards-desk, archive]
feeds: [writer, anchor]
decisions: []
---

# producer

Orchestrates the show: picks stories, orders the rundown, budgets time, and routes Caller questions.

## Contract

- `async def build_rundown(minutes: float, topics: list[str] | None = None) -> Rundown`
  - Candidates: `reporter.rank.top_stories(window_hours=producer_freshness_hours (24), min_sources=producer_min_sources (2))`, in Reporter rank order.
  - Optional `topics`: case-insensitive substring match on the story title or any source title.
  - Count: `max(1, round(minutes*60 / producer_seconds_per_story (45)))`, capped by the stories available.
  - Even split: whole seconds summing exactly to `round(minutes*60)`; earlier items get the remainder.
  - Creates a `briefings` row (`status=draft`, `target_minutes`). `NoStoriesError` if nothing matches (no briefing created).
- `Rundown`: briefing_id, minutes, items, `total_seconds`. `RundownItem`: story_id, order, target_seconds, title, sources (`StorySourceRef`).
- CLI (`app/cli.py`): `newsroom brief --minutes 3 [--topic T]... [--refresh] [--json]` runs
  `build_rundown` -> `writer.draft_script` -> `editor.review_script` and prints every line with each claim's verdict,
  score and source outlets (the judge's evidence sources, else the Writer's citations); non-approved claims show the
  judge's reason. Exit 1 on `NoStoriesError` or `WriterError`. Progress goes to stderr, the script to stdout.
- `async def handle_call(question: CallerQuestion) -> CallerAnswerPlan`: pause, run a fast Reporter -> Writer -> Editor loop, resume.

## Invariants

- Only stories inside the freshness window enter a rundown.
- A Caller answer has its own latency budget and falls back to "I'll check on that" if it overruns.

## Current state

Simple rundown done (task 2.0) in `app/producer/rundown.py`, traced as `producer/build_rundown`
with the new briefing_id. Tested with a stubbed Reporter and on Postgres
(`tests/integration/test_producer_db.py`). `newsroom brief` (task 2.5) is unit tested with a stubbed pipeline
(`tests/test_cli.py`). It has not been run live: refresh fails on Voyage 429 (see llm-gateway), and the DB holds only
integration-test stories. `handle_call` is not built yet (phase 5).

## Open questions

- (none)

## Changelog

- 2026-11-16: node created from the design doc.
- 2026-11-16: empty package scaffolded (task 0.1).
- 2026-11-17: simple `build_rundown()` with an even time split and a briefing row (task 2.0).
- 2026-11-18: `newsroom brief` CLI prints the reviewed script with verdict and sources per claim (task 2.5).
