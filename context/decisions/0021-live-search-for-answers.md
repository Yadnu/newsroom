---
id: "0021"
title: Live answers use Tavily news search with Firecrawl for full text, started in parallel with the first draft
status: accepted
date: 2026-11-19
nodes: [reporter, producer]
---

# 0021: Live answers use Tavily news search with Firecrawl for full text, started in parallel with the first draft

## Context
Task 5.4: a listener's question about something newer than, or outside, the briefing's sources got the safe line.
Decision 0003 chose a search API plus Firecrawl for live follow-ups. The user picked Tavily. The answer loop already
spends ~6-7 s drafting and judging, so a search must not add its own latency when it is not needed.

## Decision
`reporter.search_live()` calls Tavily with `topic=news` and `include_raw_content`. Results with too little text
(under 1200 chars) are fetched with Firecrawl. Results are stored as ordinary `sources` rows (trust 0.5) so the
Editor can judge answer claims against them and the Archive can trace them to the URL. Known URLs are reused and
repeat queries are cached for 10 minutes. The Producer starts the search as soon as it has the question, in parallel
with the first draft from the briefing's sources, and only waits for it when that draft is "not covered" (no
claims). Failures are soft: no key or a provider error means no live sources, and the existing fallbacks apply.

## Alternatives considered
- Search only after the first draft fails: saves search credits but adds the search to the latency of every
  uncovered question.
- Exa, or both Tavily and Exa: Tavily's news filter and raw content fit the job; one provider keeps the free tier
  simple. The adapter is small enough to swap.
- Fetch pages directly instead of Firecrawl: more code for paywalls, scripts and boilerplate removal.

## Consequences
Every answered question spends one Tavily search (cached per query). Live sources join the shared `sources` table
and may later be clustered into stories. Answer limit rises to 20 s when search is on. Cost per call is not tracked.
