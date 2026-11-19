---
id: "0019"
title: Caller screening is rules first, LLM moderation second, and fails open on LLM errors
status: accepted
date: 2026-11-19
nodes: [standards-desk, caller]
---

# 0019: Caller screening is rules first, LLM moderation second, and fails open on LLM errors

## Context
Task 5.2 screens listener questions before the Producer (5.3) answers them on air: abusive speech, off-topic
requests, and prompt injection. Questions arrive by voice, so they are short and untrusted. Groq's free tier
rate-limits often, and a voice product that ignores every caller whenever the screen's LLM call fails is broken.

## Decision
Deterministic rules run first and cost nothing: too short, too long (80 words), instruction-hijack phrasing,
insults aimed at the anchor, and the Caller's own `off_topic` intent. Anything they pass goes to one moderation call
on the gateway `classify` route (`gpt-oss-20b`), which only labels `abusive` and `injection`. If that call fails, a
question the rules passed is allowed and marked `checked_by="rules"`. Every block is logged with its reason.

## Alternatives considered
- Fail closed on LLM errors: safer in theory, but silences every listener during rate limits.
- LLM only: every question pays latency and tokens even for "ignore your instructions".
- Moderation folded into the intent classifier: one call, but mixes routing with safety and moves the gate out of
  the Standards Desk.

## Consequences
Fail-open relies on the 5.3 answer path also treating the question as data (escaped, user turn only) and answering
only from sources. Injection patterns need the whole move ("ignore ... instructions"), so news questions mentioning
"system" or "act" pass. Recall on subtle abuse depends on the LLM; measure both with the red team set (task 6.1).
