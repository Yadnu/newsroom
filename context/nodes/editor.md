---
id: editor
type: component
status: in-progress
phase: 2
code: app/editor/
depends_on: [writer, llm-gateway, data-model, archive]
feeds: [standards-desk, writer]
decisions: [0002, 0012, 0013, 0014, 0022, 0024, 0025]
---

# editor

LLM judge. Checks each claim against retrieved source passages and approves, requests a rewrite, or rejects.

## Contract

- `async def judge_claim(claim: DraftClaim) -> ClaimVerdict`: retrieves evidence, judges one claim,
  stores the verdict and evidence.
- `async def judge_script(script: Script) -> JudgedScript`: judges every claim concurrently
  (`editor_max_concurrency`), stores everything in one transaction, and sets the briefing status to `judged`.
- `ClaimVerdict`: claim_id, verdict (approved | rewrite | rejected), score 0..1 (judge confidence), reason,
  checks {supported, faithful, attributed, fresh, corroborated, consistent: bool}, sensitive,
  evidence[`EvidencePassage`: source_id, outlet, passage, score (cosine)],
  conflicts[`Conflict`: source_ids, outlets, note] (passages from 2+ sources that disagree; decision 0024).
  `JudgedScript`: briefing_id, verdicts, `count(verdict)`.
- `async def retrieve_evidence(claims: Sequence[ClaimRef]) -> dict[claim_id, list[Passage]]` and
  `chunk_text(text, size, overlap)`.
- Rubric: supported, faithful, attributed, fresh, corroborated (sensitive claims need 2 outlets), consistent
  (sources do not disagree on what the claim states, unless the claim attributes both versions). Verdict rules are
  in decisions 0012 and 0024: a failed `consistent` gives `rewrite` with the outlets named in the reason.
- `async def review_script(script: Script) -> ReviewedScript`: `judge_script()`, then up to `rewrite_max_rounds` (2)
  rounds of `writer.rewrite_line()` for lines with a non-approved claim, re-judging only new claims (decision 0013).
  `ReviewedScript`: script (current lines), verdicts (one per current claim), rounds, `count(verdict)`.
- `judge_all(claims, line_ids=None)` (judge without storing; `line_ids` claim id -> line id goes on each judge span) and `store_verdicts(verdicts, briefing_id=None)`.
- Writes `claims.verdict/score/reason/judged_at` and `claim_evidence` (replaced on re-judge).
- A failed judge call (`LLMError`, after the fallback to the same model on OpenRouter when that key is set;
  decision 0025) gives `verdict=pending`, which is not stored
  and not sent back to the Writer. A rewrite that raises `LLMError` keeps the old line (decision 0014).
- Prompts: `prompts/editor/judge_system.md` (static) and `judge_user.md` (`$today`, `$claim`, `$evidence`).
  Passages go in escaped `<evidence id="E<n>" outlet published>` blocks, in the user turn only.

## Invariants

- Judge sees only the claim and evidence, never the Writer's reasoning, line, or other claims.
- approved requires at least one `claim_evidence` row (`_store` refuses otherwise).
- Only cited, non-retracted sources are searched. No evidence means rejected, with no LLM call.
- Eval numbers below are updated after every judge prompt change.

## Current state

Tasks 2.2 and 2.3 done in `app/editor/retrieve.py`, `judge.py` and `review.py`. The `editor/judge_claim` span payload has claim_id, line_id, claim, verdict, score, reason, checks (read by the
Archive, task 3.1). Spans: `editor/review_script` (rounds,
counts) > `editor/rewrite_round` (rewritten, failed, approved). `judge_claim` spans now carry the claim text and reason. Spans: `editor/judge_script` (counts per
verdict), with a child `editor/judge_claim` per claim (verdict, score, checks, evidence count).
Unit tested with fake Groq + Voyage over `httpx.MockTransport`. `tests/integration/test_editor_db.py`
passes on Neon Postgres 18 (verdicts, evidence, briefing status, no approved claim without evidence,
re-judge replaces evidence). Live smoke run (2026-11-18, `openai/gpt-oss-120b`, 3 hand-made claims): planted
falsehood rejected; a company-reported fact stated as plain fact got rewrite (attributed). ~1.8 s per judgement. Eval set `evals/data/judge_v1.json` (task 2.4): fixed passages, so retrieval is not measured. False flag rate 0.113
(7/62): 6 are over-strict `attributed` on facts the outlets state plainly, 1 is corroboration. Misses: 2 of 6
single-outlet sensitive claims (election turnout, central-bank remark) were not marked `sensitive`.
Red team (task 6.1, decision 0022, `evals/run_redteam.py --live`): prompt `dad2a081` approved 3 of 4 satire claims;
the judge prompt now says satire, parody and humor are not evidence (`30f59e69`): 15/15 attacks caught (satire,
stale, injected passages and claims), 2 of 5 controls got rewrite (over-strict `attributed`).
Contradictions (task 6.3, decision 0024): sixth check `consistent` in the same judge call; `editor/judge_claim`
spans carry `conflicts` (outlets, note). Eval set `evals/data/contradictions_v1.json` (28 claims, 8 stories),
prompt `ca7ed1b1` (2026-11-23, 28/28): contradiction catch 1.00 (12/12), attributed versions 6/6 approved;
5 of 10 agreed facts got rewrite, all over-strict `attributed`, none from `consistent`. judge_v1 on `ca7ed1b1`
complete (130/130; 107 answered by OpenRouter after a Groq 429, decision 0025), back to the `dad2a081` numbers.

## Open questions

- (none)

## Eval results

| Date | Prompt version | Catch rate | Precision | Recall |
| --- | --- | --- | --- | --- |
| 2026-11-18 | `dad2a081` (gpt-oss-120b), judge_v1 | 1.00 (30/30) | 0.904 | 0.971 |
| 2026-11-20 | `30f59e69` (gpt-oss-120b), judge_v1, 120/130 judged (10 rate-limited) | 1.00 (27/27) | 0.881 | 0.952 |
| 2026-11-23 | `ca7ed1b1` (gpt-oss-120b, Groq + OpenRouter), judge_v1, 130/130 | 1.00 (30/30) | 0.904 | 0.971 |
| 2026-11-23 | `ca7ed1b1`, contradictions_v1, 28/28; contradiction catch 1.00 (12/12) | - | 0.706 | 1.00 |

## Changelog

- 2026-11-16: node created from the design doc.
- 2026-11-16: empty package scaffolded (task 0.1).
- 2026-11-18: evidence retrieval + `judge_claim()`/`judge_script()` with 5-check rubric (task 2.2, decision 0012).
- 2026-11-18: `review_script()` rewrite loop, max 2 rounds (task 2.3, decision 0013).
- 2026-11-18: judge failure -> pending; loop tolerates LLM errors (decision 0014).
- 2026-11-18: judge eval v1 baseline: catch 1.00, precision 0.904, recall 0.971 (task 2.4).
- 2026-11-18: judge spans carry `line_id` for the Archive (task 3.1).
- 2026-11-20: judge prompt: satire/parody is not evidence (task 6.1 red team); judge_v1 re-run.
- 2026-11-21: sixth judge check `consistent` + `ClaimVerdict.conflicts`; contradictions_v1 eval (task 6.3, decision 0024).
- 2026-11-23: judge falls back to gpt-oss-120b on OpenRouter; eval rows record the answering model (task 7.1, decision 0025).
