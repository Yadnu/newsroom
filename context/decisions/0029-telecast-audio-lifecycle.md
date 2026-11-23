---
id: "0029"
title: Telecast audio lifecycle - retention, worker jobs with in-process fallback, MP3
status: accepted
date: 2026-11-23
nodes: [press, data-model, llm-gateway]
---

# 0029: Telecast audio lifecycle - retention, worker jobs with in-process fallback, MP3

## Context
Phase 9 follow-ups to decision 0027: telecast audio files accumulated under `var/media/` with no cleanup.

## Decision
- Retention (task 9.1): audio is kept `press_telecast_retention_days` (7; 0 = forever). The worker's daily
  `cleanup_job` (03:15) and `newsroom cleanup-media [--days] [--dry-run]` delete older files, set the telecast to
  `step = 'expired'` with no `audio_path` (row and briefing stay in the Archive; asking again makes a fresh
  telecast, since only a ready telecast with its file is reused), and delete orphan files no row references once
  they are an hour old (so a job still writing is never touched).
- Worker jobs (task 9.3): `press_telecast_runner` = `auto` (default) queues `telecast_job` on the ARQ worker only
  when Redis answers and a worker has checked in (ARQ's health-check key, written every 15 s); otherwise the job
  runs in the API process as before. `worker` always queues (fails the telecast if Redis is down); `inprocess`
  never queues. Redis is tried with a 1 s timeout and no retries, and a failure is remembered for a minute.
  Starting a telecast takes a per-story advisory lock, so concurrent requests share one telecast.
- Output cap (found live in task 9.3): every chat request sends `max_tokens` per task; without it OpenRouter
  reserved the whole context against the account credit and answered 402 on every full judge prompt.

## Alternatives considered
- Queue whenever Redis is reachable: found live with a cloud Redis and no worker running; jobs sat `queued`.
- Delete the telecast rows too: loses the Archive trail of what aired.
- Size-based eviction: harder to reason about than a fixed age for a per-request cache.

## Consequences
An old telecast costs a new LLM and TTS run if someone asks for it again after a week.
