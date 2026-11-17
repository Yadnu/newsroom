---
id: "0002"
title: Separate generator and judge behind one LLM gateway
status: accepted
date: 2026-11-16
nodes: [writer, editor, llm-gateway]
---

# 0002: Separate generator and judge behind one LLM gateway

## Context
A model grading its own reasoning tends to approve it. Cost also differs: drafting is high volume, judging must be accurate.

## Decision
Writer and Editor use separate prompts and can use different models. All calls go through `app/shared/llm/`, which routes by task name from config and records tokens, cost and latency.

## Alternatives considered
- One prompt that writes and self-checks: cheaper, but weaker catch rate and no independent verdict to trace.

## Consequences
Model swaps are a config change. Every LLM call is traceable in one place.
