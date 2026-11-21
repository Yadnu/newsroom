---
id: "0023"
title: Corrections - retraction flags claims in a corrections table; aired claims get a template correction line gated by that table
status: accepted
date: 2026-11-21
nodes: [reporter, standards-desk, data-model, archive]
---

# 0023: Corrections - retraction flags claims in a corrections table; aired claims get a template correction line gated by that table

## Context
Task 6.2. `sources.retracted` existed and every reader skipped retracted sources, but nothing set it, nothing
recorded which briefings had used a source, and an aired briefing could not be corrected. The user chose a manual
retraction plus an automatic recheck, and a corrections record plus an on-air correction line.

## Decision
- `reporter.retract_source(id or url, reason)` sets `retracted`, `retracted_at`, `retraction_reason` and, in the
  same transaction, `standards_desk.flag_retraction()` writes one `corrections` row per claim that cited the source
  or was judged on it: `orphaned` (no live evidence left) or `weakened`; `on_air` when the briefing aired with the
  claim approved. Idempotent (unique source + claim).
- `reporter.recheck_sources(hours)` re-fetches live sources behind recent briefings and retracts only on HTTP
  404/410 or a publisher retraction notice. 403, 5xx and network errors are kept (counted unreachable).
- Unaired briefings need no extra step: `clear_for_air` already blocks lines without live evidence on re-clear.
- `standards_desk.queue_corrections(briefing_id)` adds one `kind='correction'` script line per pending on-air claim
  at the top of a new briefing (negative `order`), max `standards_max_corrections` (3); `newsroom brief` calls it.
  The text is a fixed template (`correction_text(claim, outlet)`), not an LLM draft, so a correction cannot add an
  unverified fact. `clear_for_air` clears such a line only if it equals the template for its `corrections` row and
  the source is still retracted (`BlockRule.correction`); the injection rule still applies first.
- Archive: `GET /archive/corrections`, `BriefingSummary.corrections`, `BriefingDetail.corrections`; the web shows a
  banner and badges.

## Alternatives considered
- A new briefing status (`flagged`): loses `aired`, and a briefing can be hit by several retractions.
- LLM-written corrections judged by the Editor: no source states "our earlier claim was wrong", so the judge would
  have nothing to approve it against; a template repeats only our own approved claim.
- Recheck through Firecrawl: costs credits per page; a plain GET is enough for 404/410 and notices.

## Consequences
`script_lines.order` may be negative. Correction lines keep the original story id (lines whose story was deleted
are not queued). Recheck has no schedule yet; it runs from the CLI.
