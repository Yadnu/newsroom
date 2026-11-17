---
id: "0003"
title: RSS for scheduled ingest, search API plus Firecrawl for live follow-ups
status: accepted
date: 2026-11-16
nodes: [reporter]
---

# 0003: RSS for scheduled ingest, search API plus Firecrawl for live follow-ups

## Context
Briefings need a steady, cheap news supply. Caller questions need fresh answers on topics the feeds may not cover.

## Decision
Scheduled ingest from RSS feeds every 15 to 30 minutes. On-demand search through Tavily or Exa, with Firecrawl for full-page content when a summary is not enough.

## Alternatives considered
- Paid news API only: rate limits and cost for the scheduled path.
- Scraping everything: fragile and riskier on terms of use.

## Consequences
Two ingest paths to test. Cache fetched pages to stay under rate limits.
