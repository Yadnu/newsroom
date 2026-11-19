---
id: llm-gateway
type: shared
status: in-progress
phase: 1
code: app/shared/llm/
depends_on: [archive, data-model]
feeds: [reporter, writer, editor, caller]
decisions: [0002, 0005, 0007, 0008, 0014, 0015]
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
- Embedding pacing (decision 0015): `Settings.embed_requests_per_minute`, `embed_tokens_per_minute` (0 = no limit)
  and `embed_batch_max_tokens` (default 100000). `embed_batches(texts, max_tokens)` and `estimate_tokens(text)`.
  `Gateway(..., sleep=, clock=)` are injectable for tests.
- Errors: `LLMConfigError` (missing key, route, or price), `LLMProviderError` (`status_code`),
  `StructuredOutputError`; all subclass `LLMError`.
- `get_gateway()` / `set_gateway(Gateway)` / `aclose()` manage the process-wide instance. `aclose()` also
  flushes the Langfuse buffer, so entry points must call it before exit.
- Langfuse export (decision 0005): `Gateway(..., langfuse=Langfuse(settings))`, on only when
  `langfuse_public_key` and `langfuse_secret_key` are both set. Settings `langfuse_host`,
  `langfuse_capture_content` (default true; false = usage only), `langfuse_flush_interval_s` (5),
  `langfuse_batch_size` (50). Langfuse trace id = the gateway's archive span id; `sessionId` = briefing id.
- Routing table `Settings.llm_routes` (task -> model) and prices `Settings.llm_prices`
  (model -> USD per 1M in/out). Both can be overridden from env as JSON.
- Fallbacks `Settings.llm_fallbacks` (task -> model; default draft/classify/answer -> `gpt-oss-120b`, no judge
  fallback): tried once after `StructuredOutputError` or a retryable provider error that outlived the retries
  (decision 0014). `Gateway.fallback_for(task)`. Fallback models must be priced.

## Invariants

- No provider SDK imports outside this folder (today: none at all, httpx only).
- Every call records tokens, cost in USD, latency, and model name, in a `traces` row via `span()`.
- Langfuse export never raises into the caller, never sends API keys, and never sends embedding texts.
- Every routed model and the embedding model must have a price, or `Gateway()` fails at startup.
- Embeddings are always `EMBEDDING_DIM` (from `app.db.models`); any other length raises an error.

## Current state

`app/shared/llm/` has `gateway.py` (`Gateway`), `schema.py` (Pydantic to strict JSON schema), and
`types.py`. Chat goes to Groq (decision 0008) with strict `json_schema`. Output that fails
validation is resampled once (Groq's `json_validate_failed` 400 counts as a failure). HTTP retries
cover 408/409/429/5xx and transport errors with exponential backoff, honor `retry-after`, and are
capped by `llm_max_attempts`. Embeddings go to Voyage in batches of at most 1000 texts and a token cap, one request at a time, paced
per minute when limits are set (decision 0015). A 429 without `retry-after` backs off 15 s per attempt. Usage is logged as a
structlog `llm.call` event and recorded on an archive span (`complete.<task>` / `embed`,
with tokens, cost, model and attempts; no prompt text). Fallback model per task (decision 0014); the span records `fallback_from`. Langfuse export (task 3.2, `langfuse.py`): plain httpx to `POST /api/public/ingestion`, no SDK; one trace
per call plus one generation per model tried (fallbacks show as an `ERROR` generation then a `DEFAULT` one),
with messages and output clipped to 20K chars each. Events are batched from a background task; send
failures are logged by status and dropped. Not yet run against a live Langfuse project (no keys in `.env`). Live Groq calls work (writer/editor smoke runs). Live Voyage embedding works
with free-tier pacing: 96 sources in under 2 minutes, no 429 (2026-11-18). Chat is not paced: Groq's free tier
allows 8000 TPM on `gpt-oss-120b` and a judge call is about 4K tokens, so at `editor_max_concurrency` 8 a live
3-minute brief left 7 of 14 claims `pending` (429 after retries, honouring `retry-after`).

## Open questions

- (none)

## Changelog

- 2026-11-16: node created from the design doc.
- 2026-11-16: empty package scaffolded (task 0.1).
- 2026-11-16: linked decision 0007 (voyage-4-lite, 1024 dims).
- 2026-11-16: task 1.2: `complete()`/`embed()` with routing, retries, cost, strict schema (decision 0008).
- 2026-11-16: `complete()`/`embed()` run inside archive spans (task 1.3).
- 2026-11-18: per-task fallback model on invalid output or exhausted retries (decision 0014).
- 2026-11-18: token-capped embed batches, per-minute pacing, longer 429 backoff (decision 0015).
- 2026-11-19: Langfuse export of chat and embed calls over the ingestion API (task 3.2, decision 0005).
