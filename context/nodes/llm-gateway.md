---
id: llm-gateway
type: shared
status: in-progress
phase: 1
code: app/shared/llm/
depends_on: [archive, data-model]
feeds: [reporter, writer, editor]
decisions: [0002, 0005, 0007, 0008, 0014]
---

# llm-gateway

The only way code talks to LLMs and embedding models: routing, retries, structured output, cost, tracing.

## Contract

- `async def complete[T: BaseModel](task: TaskName, messages: Sequence[Message], schema: type[T]) -> T`
- `async def complete_with_usage(...) -> tuple[T, Usage]` (same args)
- `async def embed(texts: Sequence[str], input_type: "document" | "query" | None = "document") -> list[list[float]]`
- `async def embed_with_usage(...) -> tuple[list[list[float]], Usage]`
- `TaskName = Literal["draft", "judge", "classify", "answer"]`; `Message` is a `{role, content}` TypedDict.
- `Usage(model, tokens_in, tokens_out, cost_usd, latency_ms, attempts)`, totalled across retries.
- Errors: `LLMConfigError` (missing key, route, or price), `LLMProviderError` (`status_code`),
  `StructuredOutputError`; all subclass `LLMError`.
- `get_gateway()` / `set_gateway(Gateway)` / `aclose()` manage the process-wide instance.
- Routing table `Settings.llm_routes` (task -> model) and prices `Settings.llm_prices`
  (model -> USD per 1M in/out). Both can be overridden from env as JSON.
- Fallbacks `Settings.llm_fallbacks` (task -> model; default draft/classify/answer -> `gpt-oss-120b`, no judge
  fallback): tried once after `StructuredOutputError` or a retryable provider error that outlived the retries
  (decision 0014). `Gateway.fallback_for(task)`. Fallback models must be priced.

## Invariants

- No provider SDK imports outside this folder (today: none at all, httpx only).
- Every call records tokens, cost in USD, latency, and model name, in a `traces` row via `span()`.
- Every routed model and the embedding model must have a price, or `Gateway()` fails at startup.
- Embeddings are always `EMBEDDING_DIM` (from `app.db.models`); any other length raises an error.

## Current state

`app/shared/llm/` has `gateway.py` (`Gateway`), `schema.py` (Pydantic to strict JSON schema), and
`types.py`. Chat goes to Groq (decision 0008) with strict `json_schema`. Output that fails
validation is resampled once (Groq's `json_validate_failed` 400 counts as a failure). HTTP retries
cover 408/409/429/5xx and transport errors with exponential backoff, honor `retry-after`, and are
capped by `llm_max_attempts`. Embeddings go to Voyage in batches of 1000. Usage is logged as a
structlog `llm.call` event and recorded on an archive span (`complete.<task>` / `embed`,
with tokens, cost, model and attempts; no prompt text). Fallback model per task (decision 0014); the span records `fallback_from`. Langfuse is not wired yet (task 3.2). Tested with `httpx.MockTransport` only; no live call has been made.

## Open questions

- (none)

## Changelog

- 2026-11-16: node created from the design doc.
- 2026-11-16: empty package scaffolded (task 0.1).
- 2026-11-16: linked decision 0007 (voyage-4-lite, 1024 dims).
- 2026-11-16: task 1.2: `complete()`/`embed()` with routing, retries, cost, strict schema (decision 0008).
- 2026-11-16: `complete()`/`embed()` run inside archive spans (task 1.3).
- 2026-11-18: per-task fallback model on invalid output or exhausted retries (decision 0014).
