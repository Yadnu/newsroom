---
id: llm-gateway
type: shared
status: planned
phase: 1
code: app/shared/llm/
depends_on: [archive]
feeds: [reporter, writer, editor]
decisions: [0002, 0007]
---

# llm-gateway

The only way code talks to LLMs and embedding models: routing, retries, structured output, cost, tracing.

## Contract

- `async def complete(task: TaskName, messages, schema: type[BaseModel]) -> BaseModel`
- `async def embed(texts: list[str]) -> list[list[float]]`
- Task-to-model routing table lives in config (cheap model for drafting, strong model for judging).

## Invariants

- No provider SDK imports outside this folder.
- Every call records tokens, cost in USD, latency, and model name.

## Current state

Empty package scaffolded at `app/shared/llm/` (docstring only, no public surface yet). Logic not started. Planned for phase 1.

## Open questions

- (none)

## Changelog

- 2026-11-16: node created from the design doc.
- 2026-11-16: empty package scaffolded (task 0.1).
- 2026-11-16: linked decision 0007 (voyage-4-lite, 1024 dims).
