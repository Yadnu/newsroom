---
id: "0026"
title: Press feed of crawler stories with paraphrased, unchecked summaries; telecasts are the fact-checked path
status: accepted
date: 2026-11-23
nodes: [press, reporter, writer, web]
---

# 0026: Press feed of crawler stories with paraphrased, unchecked summaries; telecasts are the fact-checked path

## Context
Frontend (FRONTEND_PLAN.md, task 8.1). The user wants Newsroom to work as a news press: a short view where readers
skim what the crawlers gathered, and, for a story they like, a telecast. Stories had no summary, image or category,
and only cleared, judged text may be spoken.

## Decision
- New component `app/press/` (node `press`): `GET /press/stories` (newest first, keyset cursor), and
  `fill_summaries()` run by the worker after clustering.
- Card summaries are written by `writer.summarize_story()` (~60 words, task "draft") and must pass the Standards
  Desk's copied-words rule. They are labelled "not yet fact-checked" and are never voiced. The telecast (task 8.3)
  runs the full Writer -> Editor -> Standards Desk -> Anchor path on one story.
- Images: RSS `media:thumbnail` / image `media:content` / image enclosures / first `<img>` in the body, stored as
  `sources.image_url` (http(s) only), hotlinked by the browser and credited to the outlet; gradient otherwise.
- Web: the feed lives in the existing Next.js app (`/`), the Archive moves to `/archive`; the browser reaches the
  API through a same-origin `/api` rewrite, so the backend needs no CORS.

## Alternatives considered
- Show only cleared lines from briefings as card text: only stories already in a briefing would appear (the user
  chose the crawler feed).
- Judge every summary with the Editor: an LLM call per claim for text that is not aired.
- A separate Vite app: needs CORS and its own CI and types; rejected for the existing Next.js app.

## Consequences
The feed shows unchecked text, clearly labelled. Summaries cost one small LLM call per story (capped per worker
run) and are not refreshed when a story gains sources.
