---
id: "0015"
title: Token-capped embedding batches and client-side pacing for Voyage
status: accepted
date: 2026-11-18
nodes: [llm-gateway]
---

# 0015: Token-capped embedding batches and client-side pacing for Voyage

## Context
On 2026-11-18 `newsroom stories --refresh` failed with Voyage HTTP 429 after all retries. A Voyage key
without billing allows about 3 requests and 10K tokens per minute, and the gateway sent up to 1000 texts
(up to 8000 chars each) in one request. The 429 carried no `retry-after`, so the backoff (0.5, 1, 2 s)
ended long before the minute window rolled.

## Decision
- Batches are capped by estimated tokens (`len(text) / 3`, rounded up) as well as by 1000 texts:
  `Settings.embed_batch_max_tokens` (default 100000), lowered to `embed_tokens_per_minute` when that is set.
  A single text over the cap goes alone.
- Embedding requests run one at a time per gateway. After each one, the next may start only after
  `max(60 / embed_requests_per_minute, 60 * tokens / embed_tokens_per_minute)` seconds, using the tokens
  Voyage reports (the estimate if it reports none). 0 means no limit; both default to 0 so tests and paid
  keys are unaffected. Free-tier values (3 / 9000 / 9000) are in `.env.example` and the Brief workflow.
- Any provider: a 429 without `retry-after` backs off `15 s * attempt` (capped at 30 s) instead of the
  short exponential backoff.

## Alternatives considered
- Add billing to the Voyage account: lifts the limit, still recommended, but the code should not 429 by default.
- Sleep and retry on 429 only: wastes requests from a 3 RPM budget.

## Consequences
On the free tier, the 96 pending sources (about 83K chars) embedded in under 2 minutes with no 429.
Pacing is per process; two processes sharing a key can still hit 429, which the longer backoff covers.
