---
id: editor
type: component
status: in-progress
phase: 2
code: app/editor/
depends_on: [writer, llm-gateway, data-model, archive]
feeds: [standards-desk, writer]
decisions: [0002, 0012, 0013, 0014]
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
- `async def review_script(script: Script) -> ReviewedScript`: `judge_script()`, then up to `rewrite_max_rounds` (2)
  rounds of `writer.rewrite_line()` for lines with a non-approved claim, re-judging only new claims (decision 0013).
  `ReviewedScript`: script (current lines), verdicts (one per current claim), rounds, `count(verdict)`.
- `judge_all(claims)` (judge without storing) and `store_verdicts(verdicts, briefing_id=None)`.
- Writes `claims.verdict/score/reason/judged_at` and `claim_evidence` (replaced on re-judge).
- A failed judge call (`LLMError`; the judge has no fallback model) gives `verdict=pending`, which is not stored
  and not sent back to the Writer. A rewrite that raises `LLMError` keeps the old line (decision 0014).
- Prompts: `prompts/editor/judge_system.md` (static) and `judge_user.md` (`$today`, `$claim`, `$evidence`).
  Passages go in escaped `<evidence id="E<n>" outlet published>` blocks, in the user turn only.

## Invariants

- Judge sees only the claim and evidence, never the Writer's reasoning, line, or other claims.
- approved requires at least one `claim_evidence` row (`_store` refuses otherwise).
- Only cited, non-retracted sources are searched. No evidence means rejected, with no LLM call.
- Eval numbers below are updated after every judge prompt change.

## Current state

Tasks 2.2 and 2.3 done in `app/editor/retrieve.py`, `judge.py` and `review.py`. Spans: `editor/review_script` (rounds,
counts) > `editor/rewrite_round` (rewritten, failed, approved). `judge_claim` spans now carry the claim text and reason. Spans: `editor/judge_script` (counts per
verdict), with a child `editor/judge_claim` per claim (verdict, score, checks, evidence count).
Unit tested with fake Groq + Voyage over `httpx.MockTransport`. `tests/integration/test_editor_db.py`
passes on Neon Postgres 18 (verdicts, evidence, briefing status, no approved claim without evidence,
re-judge replaces evidence). Live smoke run (2026-11-18, `openai/gpt-oss-120b`, 3 hand-made claims): planted
falsehood rejected; a company-reported fact stated as plain fact got rewrite (attributed). ~1.8 s per judgement. Eval set `evals/data/judge_v1.json` (task 2.4): fixed passages, so retrieval is not measured. False flag rate 0.113
(7/62): 6 are over-strict `attributed` on facts the outlets state plainly, 1 is corroboration. Misses: 2 of 6
single-outlet sensitive claims (election turnout, central-bank remark) were not marked `sensitive`.

## Open questions

- (none)

## Eval results

| Date | Prompt version | Catch rate | Precision | Recall |
| --- | --- | --- | --- | --- |
| 2026-11-18 | `dad2a081` (gpt-oss-120b), judge_v1 | 1.00 (30/30) | 0.904 | 0.971 |

## Changelog

- 2026-11-16: node created from the design doc.
- 2026-11-16: empty package scaffolded (task 0.1).
- 2026-11-18: evidence retrieval + `judge_claim()`/`judge_script()` with 5-check rubric (task 2.2, decision 0012).
- 2026-11-18: `review_script()` rewrite loop, max 2 rounds (task 2.3, decision 0013).
- 2026-11-18: judge failure -> pending; loop tolerates LLM errors (decision 0014).
- 2026-11-18: judge eval v1 baseline: catch 1.00, precision 0.904, recall 0.971 (task 2.4).
