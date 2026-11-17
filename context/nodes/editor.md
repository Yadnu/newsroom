---
id: editor
type: component
status: planned
phase: 2
code: app/editor/
depends_on: [writer, llm-gateway, data-model, archive]
feeds: [standards-desk, writer]
decisions: [0002]
---

# editor

LLM judge. Checks each claim against retrieved source passages and approves, requests a rewrite, or rejects.

## Contract

- `async def judge_claim(claim: Claim) -> ClaimVerdict` (verdict in approved | rewrite | rejected, score 0..1, reason, evidence passages)
- `async def judge_script(script: Script) -> JudgedScript`
- Rubric: supported, faithful, attributed, fresh, corroborated (sensitive claims need 2 outlets).

## Invariants

- Judge sees only the claim and evidence, never the Writer's reasoning.
- approved requires at least one `claim_evidence` row.
- Eval numbers below are updated after every judge prompt change.

## Current state

Empty package scaffolded at `app/editor/` (docstring only, no public surface yet). Logic not started. Planned for phase 2.

## Open questions

- (none)

## Eval results

| Date | Prompt version | Catch rate | Precision | Recall |
| --- | --- | --- | --- | --- |
| (none yet) | | | | |

## Changelog

- 2026-11-16: node created from the design doc.
- 2026-11-16: empty package scaffolded (task 0.1).
