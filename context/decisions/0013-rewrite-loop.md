---
id: "0013"
title: Rewrite loop lives in the Editor; a rewrite replaces the line's claims
status: accepted
date: 2026-11-18
nodes: [editor, writer]
---

# 0013: Rewrite loop lives in the Editor; a rewrite replaces the line's claims

## Context
Claims the Editor does not approve go back to the Writer, for at most 2 rounds. The Editor
already imports Writer types (`DraftClaim`, `Script`), so the Writer importing `ClaimVerdict`
would create an import cycle. A rewritten line also needs a clear rule for its old claims: the
air gate checks a line's claims, and a line that kept its old rejected claims could never clear.

## Decision
- `editor.review_script(script)` runs the loop: `judge_script()`, then up to `rewrite_max_rounds`
  (2) rounds. In each round, every line with a non-approved claim goes to
  `writer.rewrite_line(line, feedback, round)`, and only the new claims are judged again. A
  failed rewrite (`WriterError`) keeps the old line. Lines that are still not approved after the
  last round keep their verdicts, and the Standards Desk keeps them off the air.
- The Writer owns its input type `ClaimFeedback(text, verdict, reason)`, so it never imports the Editor.
- A rewrite keeps the line's id and order, replaces its text, deletes its old claims (cascading their
  `claim_sources` and `claim_evidence`), and inserts new `pending` claims with `rewrite_round` set.
- Rejection history is kept in the trace log: every `editor/judge_claim` span records the claim
  text, verdict and reason.

## Alternatives considered
- A `superseded` flag on `claims`, so old claims are kept: full history in SQL, but needs a migration and
  every reader must filter on it. Revisit for the rejection log API (task 3.1) if traces turn out not to be enough.
- The loop in the Producer: the Producer does not yet depend on the Editor, so it would need a new edge
  for no gain.

## Consequences
Only a line's current claims are in `claims`. Older claims of a rewritten line live only in
`traces`. The Editor's reason (LLM output that may echo source text) goes into the Writer's user
turn escaped, never into a system prompt.
