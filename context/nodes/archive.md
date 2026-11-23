---
id: archive
type: component
status: in-progress
phase: 1
code: app/archive/
depends_on: [data-model]
feeds: [web]
decisions: [0005, 0009, 0013, 0023, 0024]
---

# archive

Observability. Records every component event and builds the claim-to-source trace.

## Contract

- `def span(component: str, event: str, briefing_id: UUID | None = None, **payload) -> ContextManager[Span]`
  - Sync context manager, usable in sync and async code. Records latency, the error
    (`"Type: message"`, then re-raises), and the payload, and writes one `traces` row on exit.
  - Nesting: the inner span gets `parent_id` = outer span id and inherits `briefing_id` if none given.
  - `Span.set(**payload)` adds JSONB fields (made JSON-safe with `default=str`).
  - `Span.add_usage(tokens_in, tokens_out, cost_usd)` accumulates LLM usage.
- `current_span() -> Span | None`
- Sinks: `TraceSink` protocol (`emit(Trace)`), `DbSink` (default), `MemorySink` (tests);
  `get_sink()`, `set_sink(sink) -> previous`.
- `await start_archive()` / `await stop_archive()`: start the background writer / stop and flush.
  Every long-running process calls both. The API lifespan already does.
- `async def claim_trace(script_line_id: UUID) -> ClaimTrace` (`trace.py`): the line (briefing, story title, order,
  text, audio ms), its current `claims` as `TracedClaim` (verdict, score, reason, rewrite_round, judged_at,
  `cited: list[SourceRef]`, `evidence: list[EvidenceRef(source, passage, score)]`), and `history: list[Judgement]`:
  every `editor/judge_claim` span whose payload `line_id` is this line, oldest first. `TraceNotFoundError` if no line.
- `async def rejection_log(briefing_id=None, limit=100, include_rewrite=True) -> list[Rejection]`: judge spans with
  verdict `rejected` (and `rewrite`), newest first. `Rejection` = `Judgement` + briefing_id, line_id, line_text.
  `Judgement.current` is true while the claim still exists (false once a rewrite replaced it).
- `SourceRef(id, outlet, title, url, published_at, retracted)`. Payload parsing: `judgement_from_trace()`, `line_id_of()`.
- `Judgement.conflicts: list[ConflictRef(outlets, note)]` from the judge span payload; empty for older spans (task 6.3).
- HTTP (`routes.py`, mounted in `app/main.py`): `GET /archive/lines/{line_id}/trace` -> `ClaimTrace` (404 unknown);
  `GET /archive/rejections?briefing_id=&limit=1..500&include_rewrite=` -> `list[Rejection]`.
- `async def list_briefings(limit=50) -> list[BriefingSummary]` / `briefing_detail(id) -> BriefingDetail`
  (`briefings.py`, task 3.3). `BriefingSummary(id, created_at, status, target_minutes, lines, verdicts: dict[verdict,
  count], cost_usd, tokens_in, tokens_out, wall_ms)`; `BriefingDetail(briefing, lines: list[LineSummary(id, order,
  text, story_title, verdicts, kind, question)], stages: list[Stage])`. `BriefingNotFoundError`.
- `stages_from_spans(rows) -> list[Stage(component, steps, latency_ms, llm_calls, llm_ms, cost_usd, tokens_in,
  tokens_out, errors)]`: entry spans (parent missing or in another component) give steps and latency; llm-gateway
  spans are charged to the nearest non-gateway ancestor. `GET /archive/briefings?limit=1..200`,
  `GET /archive/briefings/{id}` (404 unknown).
- Archive read spans put the briefing id in the payload (`briefing`), never in `briefing_id`, so reading a
  briefing never changes its own timeline.
- LLM-level traces also go to Langfuse through the llm-gateway (task 3.2).
- `async def list_corrections(briefing_id=None, limit=100) -> list[CorrectionRef]` (`corrections.py`, task 6.2):
  claim, line, impact, on_air, source (outlet, url, reason, retracted_at), queued correction line and briefing.
  `GET /archive/corrections?briefing_id=&limit=1..500`; `BriefingSummary.corrections` (count) and
  `BriefingDetail.corrections`.

## Invariants

- Every component call is inside a span.
- Trace writes never block or fail the main path. `emit` only appends to a buffer, and sink errors are logged.
- Prompts and fetched content are not copied into span payloads by the gateway.

## Current state

Minimal span done (task 1.3, decision 0009). The `app/archive/` files are `span.py` (`Span`, `span`,
`current_span`) and `sink.py` (`DbSink`, `MemorySink`). The llm-gateway wraps `complete()` as
`complete.<task>` and `embed()` as `embed`, with tokens, cost and model. `app/main.py` lifespan calls
`start_archive`/`stop_archive`. `tests/conftest.py` installs a `MemorySink` for every test.
Verified against Postgres 16 + pgvector in `tests/integration/test_archive_db.py`: parent link,
usage columns, and an FK-violating row is dropped alone. Read API done (task 3.1): history and the rejection
log read trace rows (decision 0013), so they need the Editor's judge spans to carry `line_id` (from 3.1 on).
Spans recorded earlier come back with `line_id`/`line_text` null and are absent from a line's history. Both reads
run in `archive/claim_trace` / `archive/rejection_log` spans. Unit tests cover payload parsing and routes;
`tests/integration/test_archive_trace_db.py` covers the SQL (CI only; no local test DB). Read-only live check on
the dev DB (briefing `3873a08c`): a sentence traced to its TechCrunch URL; 7 rejections listed.
Briefing timeline done (task 3.3) for the web dashboard; live on `3873a08c`: producer 1.2 s, writer 33 s
(7 LLM calls), editor 175 s (25 calls, 6 errors), $0.011 total. Covered in the same integration test file.

## Open questions

- (none)

## Changelog

- 2026-11-16: node created from the design doc.
- 2026-11-16: empty package scaffolded (task 0.1).
- 2026-11-16: `span()`, buffered `DbSink`, gateway spans, lifespan wiring (task 1.3, decision 0009).
- 2026-11-18: `claim_trace()`, `rejection_log()` and `/archive` routes (task 3.1).
- 2026-11-19: briefing list/detail with per-stage latency and cost; read spans off the timeline (task 3.3).
- 2026-11-19: `LineSummary.kind` / `question` so answer lines show in the timeline (task 5.3).
- 2026-11-21: corrections read API (task 6.2, decision 0023).
- 2026-11-21: `Judgement.conflicts` read from judge spans (task 6.3, decision 0024).
