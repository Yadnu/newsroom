---
id: archive
type: component
status: planned
phase: 1
code: app/archive/
depends_on: [data-model]
feeds: [web]
decisions: [0005]
---

# archive

Observability. Records every component event and builds the claim-to-source trace.

## Contract

- `def span(component: str, event: str, briefing_id: UUID) -> ContextManager[Span]` (latency, cost, payload)
- `async def claim_trace(script_line_id: UUID) -> ClaimTrace`
- LLM-level traces also go to Langfuse via the llm-gateway.

## Invariants

- Every component call is inside a span.
- Trace writes never block or fail the main path.

## Current state

Empty package scaffolded at `app/archive/` (docstring only, no public surface yet). Logic not started. Planned for phase 1 (minimal span), expanded in phase 3.

## Open questions

- (none)

## Changelog

- 2026-11-16: node created from the design doc.
- 2026-11-16: empty package scaffolded (task 0.1).
