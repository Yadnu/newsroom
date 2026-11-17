---
id: "0006"
title: Markdown context graph shared by Claude Code and Cursor
status: accepted
date: 2026-11-16
nodes: []
---

# 0006: Markdown context graph shared by Claude Code and Cursor

## Context
Work moves between Claude Code and Cursor across many sessions. Each new session starts cold.

## Decision
Project memory lives in `context/` as markdown: one node file per component with edges in frontmatter, decision records, and a STATE file with a handoff note. `AGENTS.md` holds the rules; `CLAUDE.md` and `.cursor/rules/` point at it. `scripts/context_graph.py` builds the index and checks links.

## Alternatives considered
- One large CLAUDE.md: loads everything every time and goes stale.
- A graph database or MCP memory server: more setup, not readable in a PR.

## Consequences
Context changes are reviewed in git like code. Agents must run the sync step, or the graph drifts.
