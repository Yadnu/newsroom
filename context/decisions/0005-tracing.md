---
id: "0005"
title: Own traces table for the product, Langfuse for LLM debugging
status: accepted
date: 2026-11-16
nodes: [archive, llm-gateway]
---

# 0005: Own traces table for the product, Langfuse for LLM debugging

## Context
The claim trace is a user-facing feature, so it must live in our database. LLM prompt debugging is a developer need.

## Decision
`traces` and `claim_evidence` tables in Postgres power the product UI. The LLM gateway also sends call-level traces to Langfuse.

## Alternatives considered
- Langfuse only: cannot join cleanly with script lines and audio timestamps for the player.

## Consequences
Two trace sinks. Archive writes must be async and never fail the main path.
