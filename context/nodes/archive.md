---
id: archive
type: component
status: in-progress
phase: 1
code: app/archive/
depends_on: [data-model]
feeds: [web]
decisions: [0005, 0009]
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
- Planned (phase 3): `async def claim_trace(script_line_id: UUID) -> ClaimTrace`.
- LLM-level traces also go to Langfuse through the llm-gateway (phase 3).

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
usage columns, and an FK-violating row is dropped alone. `claim_trace()` is not built yet (task 3.1).

## Open questions

- (none)

## Changelog

- 2026-11-16: node created from the design doc.
- 2026-11-16: empty package scaffolded (task 0.1).
- 2026-11-16: `span()`, buffered `DbSink`, gateway spans, lifespan wiring (task 1.3, decision 0009).
