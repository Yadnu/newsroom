---
id: "0024"
title: Contradictions - a sixth judge check, consistent, in the same call; disagreeing sources mean rewrite with both outlets named
status: accepted
date: 2026-11-21
nodes: [editor, archive]
---

# 0024: Contradictions - a sixth judge check, consistent, in the same call; disagreeing sources mean rewrite with both outlets named

## Context
Task 6.3. The judge checked a claim against up to 4 passages but nothing noticed when the passages disagreed with
each other (120 vs 200 job cuts): it cited the passage that matched and approved the claim as plain fact.

## Decision
- The judge rubric gains `consistent`: the passages do not disagree, with each other or with the claim, on a fact
  the claim states. It passes when the claim itself reports both versions and who says what. The model also
  returns `conflicts` (passage ids that disagree, and a note).
- Code keeps only conflicts naming known passages from 2+ distinct sources (`ClaimVerdict.conflicts`), and the
  reason names the outlets ("consistent: sources disagree (Ledger Tech vs Northwire: 120 vs 200 jobs)").
- A failed `consistent` check gives `rewrite` (decision 0012), not `rejected`: the fact may air once both versions
  are attributed. The existing rewrite loop (decision 0013) passes the reason to the Writer; a claim still
  inconsistent after the last round stays `rewrite` and the Standards Desk keeps it off air.
- Conflicts go on the `editor/judge_claim` span and `archive.Judgement.conflicts`; the web trace panel shows them.
- Eval set `evals/data/contradictions_v1.json` (kinds `contradicted`, `conflict_attributed`, `supported`);
  `contradiction_catch` in the summary.

## Alternatives considered
- A separate pairwise contradiction call per claim: catches the same thing at one more LLM call per claim and
  more latency on the answer path.
- Cross-claim contradiction across the whole briefing: a different problem (our own lines disagreeing); not needed
  while every claim is judged against its own sources.
- Reject on conflict: drops facts that are newsworthy precisely because sources disagree.

## Consequences
Judge prompt and output schema change, so judge_v1 is re-run. A model that fails `consistent` without naming a
valid pair still forces a rewrite (no conflict listed).
