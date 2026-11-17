---
id: "0010"
title: Incremental greedy centroid clustering for stories
status: accepted
date: 2026-11-16
nodes: [reporter]
---

# 0010: Incremental greedy centroid clustering for stories

## Context
Task 1.5 groups sources about the same event into `stories`. Ingest runs every 15 minutes and adds
a few dozen sources each time, so clustering must be incremental. Story ids must stay stable
because script lines and claims point at them.

## Decision
Each run takes the unassigned, embedded, non-retracted sources from the last
`reporter_cluster_window_hours` (default 24), oldest first. Each one joins the recent story with
the highest cosine similarity if that similarity is at least `reporter_cluster_threshold` (default
0.80). Otherwise it starts a new story named after that source. Centroid = normalized mean of member embeddings.
Assigned sources never move. A Postgres advisory lock serializes runs. The math uses numpy in-process.

## Alternatives considered
- Full re-clustering (HDBSCAN or agglomerative) each run: better groups, but story ids churn and it adds scikit-learn.
- Nearest-neighbour lookup per source through the HNSW index: no in-memory matrix, but it ignores
  sources in the same batch and makes one query per source. The in-memory approach is fine at a few
  thousand stories per day.

## Consequences
Results depend on order and never merge two stories after the fact. The 0.80 threshold is a guess
that has not been calibrated on voyage-4-lite news embeddings. Check it on the first live run.
Stories older than the window stop attracting new sources.
