---
id: producer
type: component
status: in-progress
phase: 2
code: app/producer/
depends_on: [reporter, caller, standards-desk, archive]
feeds: [writer, anchor]
decisions: [0020, 0021, 0023]
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
  `build_rundown` -> `writer.draft_script` -> `editor.review_script` -> `standards_desk.clear_for_air` and prints every
  line (blocked lines struck through with `BLOCKED <rule>: reason`) with each claim's verdict,
  score and source outlets (the judge's evidence sources, else the Writer's citations); non-approved claims show the
  judge's reason. JSON adds `cleared` and per-line `on_air` / `block`. Exit 1 on `NoStoriesError`, `WriterError`,
  or when nothing clears (the report is still printed). After review, `queue_corrections` puts pending on-air
  corrections first (story `Corrections`) (task 6.2, decision 0023).
- `async def answer_question(question, script: ClearedScript) -> AnswerResult(cleared, fallback, total_ms)`
  (`answer.py`, task 5.3, decision 0020): sources of the question's story (else the whole briefing, best
  `producer_answer_max_sources` 6) -> `writer.draft_answer` -> `store_answer` -> `editor.judge_all` + `store_verdicts`
  -> `clear_for_air(mark_briefing=False)`. Nothing cleared, no sources, `WriterError`/`LLMError`, or over
  `producer_answer_timeout_s` (12) -> the fixed claimless `SAFE_LINE`. Span `producer/answer` (sources/draft/judge/
  clear/total ms, fallback, over_budget vs `producer_answer_budget_s` 8).
  Live search (task 5.4, `producer_answer_search` on): `reporter.search_live(question + story title)` starts in
  parallel with the first draft; only if that draft has no claims (not covered) is it awaited, and the answer is
  redrafted from the live sources first, then the story's. Otherwise the search is cancelled. Limit with search:
  `producer_answer_search_timeout_s` (20). Span adds `searched`, `live_sources`, `search_ms`, `live_draft_ms`.
- `async def handle_question(question, script, session)`: allowed `follow_up`/`background` -> `answer_status`
  thinking -> answer -> `answer_status` answering|unsure (+ lines) -> `session.interject` -> `session.resume()`;
  anything else -> `declined` and resume. Import from `app.producer.answer` (the Writer imports `app.producer`).
- CLI `newsroom speak <briefing_id> [--out brief.wav]`: `clear_stored` -> `anchor.speak` into a WAV file; prints each
  line's start/end ms. Exit 1 for an unknown briefing, nothing cleared, or TTS not configured. Progress goes to stderr, the script to stdout.
  `.github/workflows/brief.yml` (manual dispatch: minutes, topic, refresh; free-tier embed pacing) runs it live with repo secrets
  `NEWSROOM_DATABASE_URL`, `NEWSROOM_GROQ_API_KEY`, `NEWSROOM_VOYAGE_API_KEY`; uploads `brief.json` + logs, writes a job summary.
- `async def handle_call(question: CallerQuestion) -> CallerAnswerPlan`: pause, run a fast Reporter -> Writer -> Editor loop, resume.

## Invariants

- Only stories inside the freshness window enter a rundown.
- A Caller answer has its own latency budget and falls back to "I'll check on that" if it overruns.

## Current state

Simple rundown done (task 2.0) in `app/producer/rundown.py`, traced as `producer/build_rundown`
with the new briefing_id. Tested with a stubbed Reporter and on Postgres
(`tests/integration/test_producer_db.py`). `newsroom brief` (task 2.5) is unit tested with a stubbed pipeline
(`tests/test_cli.py`). Live run 2026-11-18 (`--minutes 3 -t Altman -t Anthropic`, 3m17s):
briefing `3873a08c`, 16 lines printed with verdict and sources per claim; approved 5, rewrite 1, rejected 1, pending 7
(Groq TPM 429 on the judge). The Anthropic story was skipped (`StructuredOutputError` on draft and fallback). `handle_call` is not built yet (phase 5).

## Open questions

- (none)

## Changelog

- 2026-11-16: node created from the design doc.
- 2026-11-16: empty package scaffolded (task 0.1).
- 2026-11-17: simple `build_rundown()` with an even time split and a briefing row (task 2.0).
- 2026-11-18: `newsroom brief` CLI prints the reviewed script with verdict and sources per claim (task 2.5).
- 2026-11-18: manual `Brief` GitHub workflow runs the live pipeline.
- 2026-11-19: `newsroom brief` clears the script for air and shows blocked lines (task 4.1).
- 2026-11-19: `newsroom speak <briefing_id> [--out file.wav]` voices a stored briefing (task 4.2).
- 2026-11-19: `newsroom ask --briefing <id> --wav q.wav` transcribes and classifies a question (task 5.1).
- 2026-11-19: answers listener questions on air with the full fact-check, then resumes (task 5.3).
- 2026-11-19: answers fall back to live search when the briefing's sources don't cover them (task 5.4).
- 2026-11-21: `newsroom brief` airs queued corrections first (task 6.2, decision 0023).
- 2026-11-23: `newsroom` switches cp1252 stdout/stderr to UTF-8 (`utf8_streams`), so `brief` no longer crashes printing to a Windows pipe.
