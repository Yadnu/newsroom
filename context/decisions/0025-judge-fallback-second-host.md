---
id: "0025"
title: Judge falls back to the same model on a second host (OpenRouter); a 429 with a fallback fails over at once
status: accepted
date: 2026-11-23
nodes: [llm-gateway, editor]
---

# 0025: Judge falls back to the same model on a second host (OpenRouter); a 429 with a fallback fails over at once

## Context
Decision 0014 gave the judge no fallback, because a weaker judge is worse than no verdict. On Groq's free tier
(8000 TPM and a daily cap for `gpt-oss-120b`) that left most judge calls `pending`: 17 of 23 claims in briefing
`e4f4a284`, and 6 of 130 judge_v1 cases on 2026-11-21. Every failed call also spent about 75 s waiting out 429
retries (15 + 30 + 30 s) before giving up.

## Decision
- A model string may name its host: `openrouter:<model id>` goes to OpenRouter (OpenAI-compatible,
  `openrouter_base_url`, `NEWSROOM_OPENROUTER_API_KEY`). No prefix, or an unknown one, means Groq, so existing
  routes and ids like `x/y:free` are unchanged. Prices are keyed by the full string.
- The judge's fallback is **the same model** on that host: `openrouter:openai/gpt-oss-120b`. 0014's rule (never a
  weaker judge) holds. OpenRouter requests send `provider.require_parameters = true`, so they only route to
  hosts that honour strict `json_schema`.
- A fallback whose host has no key is ignored (`fallback_for()` returns None). Without the key, the judge behaves
  as before.
- When a task has a usable fallback, a 429 on the primary fails over at once instead of retrying. 5xx and
  transport errors still retry first. The fallback call keeps the normal retries.
- Spans already record `fallback_from` and the answering `model`. The judge eval records the answering model per
  case and a count per model in the summary.

## Alternatives considered
- Cerebras or a generic OpenAI-compatible host: the user chose OpenRouter (one key, many hosts of the model).
- Client-side pacing of judge calls under Groq's TPM: still capped by the daily limit, and slower.
- A different, smaller judge model as fallback: rejected for the same reason as in 0014.

## Consequences
- Verdicts can come from two hosts of the same weights. Eval rows say which one, so a drift between hosts would
  show.
- OpenRouter's price depends on the host it routes to; the recorded list price (0.04 / 0.18 USD per 1M) is
  approximate.
- Draft, classify and answer also fail over to their Groq fallback on the first 429.
