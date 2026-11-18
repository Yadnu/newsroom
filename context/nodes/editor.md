---
id: editor
type: component
status: in-progress
phase: 2
code: app/editor/
depends_on: [writer, llm-gateway, data-model, archive]
feeds: [standards-desk, writer]
decisions: [0002, 0012]
---

# editor

LLM judge. Checks each claim against retrieved source passages and approves, requests a rewrite, or rejects.

## Contract

- `async def judge_claim(claim: DraftClaim) -> ClaimVerdict`: retrieves evidence, judges one claim,
  stores the verdict and evidence.
- `async def judge_script(script: Script) -> JudgedScript`: judges every claim concurrently
  (`editor_max_concurrency`), stores everything in one transaction, and sets the briefing status to `judged`.
- `ClaimVerdict`: claim_id, verdict (approved | rewrite | rejected), score 0..1 (judge confidence), reason,
  checks {supported, faithful, attributed, fresh, corroborated: bool}, sensitive,
  evidence[`EvidencePassage`: source_id, outlet, passage, score (cosine)].
  `JudgedScript`: briefing_id, verdicts, `count(verdict)`.
- `async def retrieve_evidence(claims: Sequence[ClaimRef]) -> dict[claim_id, list[Passage]]` and
  `chunk_text(text, size, overlap)`.
- Rubric: supported, faithful, attributed, fresh, corroborated (sensitive claims need 2 outlets).
  Verdict rules are in decision 0012.
- Writes `claims.verdict/score/reason/judged_at` and `claim_evidence` (replaced on re-judge).
- Prompts: `prompts/editor/judge_system.md` (static) and `judge_user.md` (`$today`, `$claim`, `$evidence`).
  Passages go in escaped `<evidence id="E<n>" outlet published>` blocks, in the user turn only.

## Invariants

- Judge sees only the claim and evidence, never the Writer's reasoning, line, or other claims.
- approved requires at least one `claim_evidence` row (`_store` refuses otherwise).
- Only cited, non-retracted sources are searched. No evidence means rejected, with no LLM call.
- Eval numbers below are updated after every judge prompt change.

## Current state

Task 2.2 done in `app/editor/retrieve.py` and `judge.py`. Spans: `editor/judge_script` (counts per
verdict), with a child `editor/judge_claim` per claim (verdict, score, checks, evidence count).
Unit tested with fake Groq + Voyage over `httpx.MockTransport`. `tests/integration/test_editor_db.py`
passes on Neon Postgres 18 (verdicts, evidence, briefing status, no approved claim without evidence,
re-judge replaces evidence). Live smoke run (2026-11-18, `openai/gpt-oss-120b`, 3 hand-made claims): planted
falsehood rejected; a company-reported fact stated as plain fact got rewrite (attributed). ~1.8 s per judgement. No eval set yet (task 2.4).

## Open questions

- (none)

## Eval results

| Date | Prompt version | Catch rate | Precision | Recall |
| --- | --- | --- | --- | --- |
| (none yet) | | | | |

## Changelog

- 2026-11-16: node created from the design doc.
- 2026-11-16: empty package scaffolded (task 0.1).
- 2026-11-18: evidence retrieval + `judge_claim()`/`judge_script()` with 5-check rubric (task 2.2, decision 0012).
