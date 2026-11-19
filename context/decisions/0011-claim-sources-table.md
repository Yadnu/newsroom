---
id: "0011"
title: Writer citations in claim_sources, separate from Editor evidence
status: accepted
date: 2026-11-17
nodes: [data-model, writer]
---

# 0011: Writer citations in claim_sources, separate from Editor evidence

## Context
The Writer contract says each claim carries "the source ids it relied on". The schema had nowhere
to store this. `claim_evidence` holds the Editor's verified passages, and the air gate requires
at least one `claim_evidence` row for approval. If the Writer wrote to that table, a claim could
satisfy the gate with no judging at all.

## Decision
A new table, `claim_sources(claim_id FK claims ON DELETE CASCADE, source_id FK sources ON DELETE
RESTRICT, PK both)`, with an index on `source_id`, added in migration `f41cfce23b88`. Only the
Writer writes it. The Editor uses it to pick which sources to retrieve evidence from, and still
writes its own `claim_evidence`.

## Alternatives considered
- `claims.cited_source_ids UUID[]`: one column, but no FK integrity, and the retraction lookup ("which claims cited
  source X", task 6.2) becomes an array scan.
- Writing citations into `claim_evidence` with an empty passage: this would defeat the air gate.

## Consequences
A cited source cannot be deleted. Retract it instead, as with evidence. The retraction pipeline
can find affected claims with an indexed join.
