---
id: "0009"
title: Spans go to a buffered in-process sink, written in background batches
status: accepted
date: 2026-11-16
nodes: [archive]
---

# 0009: Spans go to a buffered in-process sink, written in background batches

## Context
Decision 0005 says trace writes must never block or fail the main path. `span()` wraps every
component step, including LLM calls inside the voice loop, so a synchronous INSERT per span
would add a database round trip to each one.

## Decision
`span()` is a sync context manager that hands the finished `Trace` to a process-wide sink.
The default `DbSink` adds it to a bounded in-memory buffer (10k). A background task started by
`start_archive()` flushes every 0.5 s in batches of 200. If a batch fails, it is retried row by
row, and failing rows are dropped with a warning. When the buffer is full, the oldest trace is dropped.

## Alternatives considered
- One INSERT per span: simplest, but adds latency to every step and fails when the database is down.
- Redis/ARQ queue: survives a crash, but adds another hop and another failure mode for a minimal version.

## Consequences
Traces still buffered when a process crashes are lost, and `stop_archive()` flushes them on clean
shutdown. Every process that emits spans (API, workers, CLI) must call `start_archive()` and
`stop_archive()`, or traces stay in memory until the buffer drops them. Tests install a `MemorySink`.
