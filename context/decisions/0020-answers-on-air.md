---
id: "0020"
title: On-air answers are judged script lines spoken as interjections, with a fixed safe line on failure
status: accepted
date: 2026-11-19
nodes: [producer, writer, anchor, data-model, standards-desk]
---

# 0020: On-air answers are judged script lines spoken as interjections, with a fixed safe line on failure

## Context
Task 5.3 answers a listener's allowed question on air and resumes the briefing. The non-negotiable "no claim
reaches the Anchor without approved + evidence" applies to answers too, and the user chose the full check on every
answer claim. A listener is waiting in silence, so the loop needs a latency budget and a way out.

## Decision
An answer is drafted by the Writer from the story's sources (or the whole briefing's), stored as `script_lines`
with `kind='answer'` and the question, judged by the Editor like any claim, and cleared by the Standards Desk
without touching the briefing status. The Anchor speaks it as an interjection on the same pipeline and audio clock,
then resumes the briefing at the interrupted line. If nothing clears, there are no sources, a step fails, or the loop
passes 12 s, the Anchor says one fixed claimless line ("I can't confirm more on that from our sources yet."), which
passes the gate as a sign-post. The budget is 8 s (logged, not enforced). Push-to-talk stays the barge-in.

## Alternatives considered
- Reuse only claims already approved in the briefing: instant, but cannot answer anything new.
- A separate `answers` table: duplicates claims, evidence and the Archive trace that script lines already have.
- Fail silently: the listener would not know the question was heard.

## Consequences
Answers trace in the Archive like any sentence and are excluded from replays (`load_script` reads `kind='script'`).
Latency is dominated by retrieval embeddings and the judge; with Groq's free-tier judge limit an answer can fall back
to the safe line. Live search for questions beyond the briefing's sources is task 5.4.
