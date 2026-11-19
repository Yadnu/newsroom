---
id: "0012"
title: Editor retrieves evidence from on-the-fly chunks; code computes the verdict
status: accepted
date: 2026-11-18
nodes: [editor]
---

# 0012: Editor retrieves evidence from on-the-fly chunks; code computes the verdict

## Context
The Editor needs passages, not whole articles, to judge a claim, and the schema has no chunk
table. Its LLM judge must also apply the rubric the same way every time, including the rule
that sensitive claims need 2 outlets.

## Decision
- Retrieval: only the claim's cited (`claim_sources`), non-retracted sources are searched. Each one
  (title + content, capped at `editor_source_max_chars`) is split into overlapping chunks
  (`editor_chunk_chars` 700, `editor_chunk_overlap` 120, cut at sentence ends when possible).
  Chunks are embedded as `document`, claims as `query`, once per `judge_script()` call, and
  the top `editor_top_k` (4) by cosine are kept. Chunk vectors are not stored.
- Verdict: the model returns pass/fail plus a note for each of the 5 checks, `sensitive`, the cited
  passage ids, and a confidence. Code maps these to a verdict: no passages, `supported` failed,
  or no valid passage cited -> rejected; any other failed check -> rewrite; else approved.
  Corroboration is computed in code (distinct outlets among cited passages, >= 2) and only
  applies to sensitive claims. Cited passages are stored as `claim_evidence` for approved
  and rewrite verdicts; re-judging replaces them.

## Alternatives considered
- A `source_chunks` table with stored embeddings and an HNSW index: faster when sources are
  reused, but needs a migration and backfill. Revisit if embedding cost or latency matters.
- Letting the model output the verdict directly: less consistent, and the 2-outlet rule could not
  be enforced.

## Consequences
Every judged briefing pays to embed its cited sources again. Rubric changes are code changes
and need an eval rerun.
