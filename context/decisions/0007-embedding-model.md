---
id: "0007"
title: Voyage voyage-4-lite embeddings at 1024 dimensions
status: accepted
date: 2026-11-16
nodes: [data-model, llm-gateway]
---

# 0007: Voyage voyage-4-lite embeddings at 1024 dimensions

## Context
Task 1.1 needs a fixed vector dimension for the pgvector columns and HNSW index. Embeddings are used
for source dedupe, story clustering, and evidence retrieval for the Editor. Volume is high (every
ingested article and passage), so cost per token matters more than top-of-leaderboard quality.

## Decision
Embed with Voyage `voyage-4-lite` through `app/shared/llm/embed()`, at 1024 dimensions, cosine
distance. The model name is a config value; the dimension is fixed in the schema.

## Alternatives considered
- `voyage-4` / `voyage-4-large`: better retrieval, about 3x to 6x the price. Same 1024-dim output, so
  a later swap needs a re-embed but no migration.
- OpenAI `text-embedding-3-small` (1536 dims): comparable, but adds a second provider account.
- Local sentence-transformers: free, but a heavy dependency and weaker on news retrieval.

## Consequences
1024 dims stays well under pgvector's 2000-dim HNSW limit. Changing the model means re-embedding all
rows; changing the dimension means a migration. Needs a `NEWSROOM_VOYAGE_API_KEY` in config.
Prices came from third-party listings (about $0.02 per 1M tokens), so confirm on Voyage's own
pricing page before budgeting.
