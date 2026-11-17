---
id: "0001"
title: Postgres with pgvector as the single datastore
status: accepted
date: 2026-11-16
nodes: [data-model]
---

# 0001: Postgres with pgvector as the single datastore

## Context
The trace chain (source to claim to spoken line) is relational, and dedupe and claim matching need vector search.

## Decision
One Postgres 16 database with pgvector for both relational data and embeddings.

## Alternatives considered
- Separate vector DB (Qdrant, Pinecone): a second system to keep in sync for little gain at this scale.

## Consequences
Joins across traces and evidence stay simple. Revisit if vector volume passes a few million rows.
