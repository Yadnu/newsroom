---
id: "0029"
title: Telecast audio lifecycle - retention, worker jobs with in-process fallback, MP3
status: accepted
date: 2026-11-23
nodes: [press, data-model]
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

## Alternatives considered
- Delete the telecast rows too: loses the Archive trail of what aired.
- Size-based eviction: harder to reason about than a fixed age for a per-request cache.

## Consequences
An old telecast costs a new LLM and TTS run if someone asks for it again after a week.
