---
id: "0008"
title: Groq gpt-oss models for chat, over plain HTTP
status: accepted
date: 2026-11-16
nodes: [llm-gateway]
---

# 0008: Groq gpt-oss models for chat, over plain HTTP

## Context
Task 1.2 needed a chat provider for `complete()`. The owner wanted a free option for development.
`complete()` returns a Pydantic model, so the provider must enforce a JSON schema.

## Decision
Use Groq's OpenAI-compatible `/chat/completions` endpoint with strict `json_schema` response format.
Routing in `Settings.llm_routes` sends `draft`, `classify` and `answer` to `openai/gpt-oss-20b`, and
`judge` to `openai/gpt-oss-120b`. Both providers (Groq, Voyage) are called with httpx, so the repo
has no provider SDK.

## Alternatives considered
- Gemini free tier: also free, but on that tier prompts may be used for training, and it has a different structured-output API.
- Anthropic / OpenAI: no ongoing free tier.
- Ollama (local): free with no rate limits, but small local models make weak judges, and it needs a GPU.
- `openai` SDK pointed at Groq: an extra dependency for one POST call, and its retry rules sit outside our accounting.

## Consequences
Moving to any OpenAI-compatible host means changing `groq_base_url` and `llm_routes`. Free-tier
rate limits will throttle large eval runs, so the gateway retries 429s and honors `retry-after`.
Strict mode supports only some models (gpt-oss-20b/120b, at the time of writing). Cost is recorded
at Groq list price ($0.075/$0.30 and $0.15/$0.60 per 1M tokens, read on 2026-11-16), even on the
free tier.
