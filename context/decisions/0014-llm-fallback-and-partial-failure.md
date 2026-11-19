---
id: "0014"
title: Per-task fallback model; one failed story or claim never sinks a briefing
status: accepted
date: 2026-11-18
nodes: [llm-gateway, writer, editor]
---

# 0014: Per-task fallback model; one failed story or claim never sinks a briefing

## Context
Live Groq runs (2026-11-18) showed `openai/gpt-oss-20b` sometimes failing strict JSON twice in a row
(`StructuredOutputError`) and rate limits forcing retries of up to 26 s. A single failure aborted
all of `draft_script()` (it was inside one `asyncio.gather`) or `judge_script()`.

## Decision
- Gateway: `Settings.llm_fallbacks` (task -> model, overridable from env as JSON). When the routed model
  raises `StructuredOutputError`, or an `LLMProviderError` that is retryable (408/409/429/5xx or
  transport) after all retries, the call is tried once on the fallback. Auth and bad-request errors
  never fall back. Defaults: draft, classify, answer -> `openai/gpt-oss-120b`; **judge has none**,
  because a weaker judge is worse than no verdict. Fallback models must be priced or `Gateway()` fails.
  The span records `fallback_from` and `fallback_reason`, and `model` is set to the model that answered.
- Writer: `draft_script()` skips a story whose segment fails (`WriterError` or `LLMError`), logs
  `writer.story_failed`, and raises `WriterError` only if no story could be drafted.
- Editor: a failed judge call gives `verdict=pending`, which is not stored and never airs. The rewrite
  loop does not send pending claims to the Writer, and a rewrite that raises `LLMError` keeps the old line.

## Alternatives considered
- More resamples on the same model: same failure mode, more latency.
- A second provider: more keys and code, not needed yet.

## Consequences
A briefing can come out shorter than its rundown. The `failed` count on the `writer/draft_script` span shows
by how much. Tokens spent on a failed primary attempt are not counted in `Usage`. This was already true
for `StructuredOutputError`.
