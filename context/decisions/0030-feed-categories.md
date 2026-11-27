---
id: "0030"
title: Story categories come from the feeds, by majority of a story's live sources
status: accepted
date: 2026-11-26
nodes: [press, reporter, data-model, web]
---

# 0030: Story categories come from the feeds, by majority of a story's live sources

## Context

Task 9.5: the Press feed needs categories to filter by. Stories had none, and the plan (FRONTEND_PLAN.md) kept the
category bar hidden until they existed. All 16 feeds are tech outlets, but they lean differently (AI desks,
general tech, business wires, science).

## Decision

- Each `FeedConfig` names a category (default `Tech`); ingest stores it on `sources.category` (migration
  `c9e2a4b6d815`) and backfills it on existing rows that are still in a feed.
- A story's category is computed at read time in SQL (`press.feed.story_categories()`): the most common category
  among its live sources, ties to the one seen most recently, then by name. Stories whose sources have none have no
  category and appear only under All.
- `GET /press/stories?category=` filters; `GET /press/categories` counts feed-eligible stories per category. The web
  bar shows when 2+ categories have stories; the choice lives in `?category=` so a filtered feed can be shared.

## Alternatives considered

- LLM classification per story: one more call per story on the free tier, and labels that drift between runs.
- Storing the category on `stories`: must be rewritten whenever clustering adds a source or one is retracted; the
  read-time window function stays correct with no extra write path.
- Keyword rules on titles: brittle, and a feed's desk is already an editor's choice.

## Consequences

A story's label follows its outlets, not its content (a Bloomberg AI story can read Business). Sources ingested
before this change and no longer in a feed keep a NULL category. New categories need only a feed entry.
