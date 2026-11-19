---
id: "0016"
title: Standards Desk v1 uses deterministic rules and an unforgeable ClearedScript
status: accepted
date: 2026-11-19
nodes: [standards-desk, anchor]
---

# 0016: Standards Desk v1 uses deterministic rules and an unforgeable ClearedScript

## Context
Between the Editor and the Anchor nothing enforced the non-negotiable "no claim reaches the Anchor without
`approved` and evidence": a `ReviewedScript` still carries pending and rejected lines (live: 7 of 14 claims
pending). The Writer may also leave a line unclaimed, and an unclaimed line is never fact-checked. Groq's free tier
(8000 TPM) is already the bottleneck for the judge, so another LLM pass per line is expensive.

## Decision
`clear_for_air(reviewed)` applies fixed rules per line: claims stored as approved with evidence from a non-retracted
source (read back from Postgres); a line without claims must be a sign-post of at most 10 words with no digits,
quotes, names or reported speech; quotes under 15 words; no 12-word run copied from a cited source outside quotes;
no evaluative word (small lexicon) in an unattributed sentence. A story whose every factual line is blocked loses its
transitions. Blocked lines are logged as `standards-desk/block_line` spans and left in `script_lines`.
`ClearedScript` cannot be constructed outside `clear_for_air` (its constructor raises; a private token issues it).

## Alternatives considered
- LLM classifier for opinion and copying: better recall, but one more call per line under an 8000 TPM limit and
  needs its own eval set. Revisit with the red team set (task 6.1).
- Trust the in-memory verdicts: cheaper, but the gate would then check what the code believes, not what is stored.
- Delete blocked lines: loses the Archive's record of what was cut and why.

## Consequences
The rules are strict: on the live briefing `3873a08c` only the 5 lines with approved claims clear, and three
unclaimed commentary lines are cut. The opinion lexicon and name heuristic will miss some cases and flag a few
harmless sign-posts; tune them against task 6.1. Thresholds are settings (`standards_max_copied_words`,
`standards_max_transition_words`).
