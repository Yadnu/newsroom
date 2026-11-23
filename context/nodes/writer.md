---
id: writer
type: component
status: in-progress
phase: 2
code: app/writer/
depends_on: [producer, editor, llm-gateway, data-model, archive]
feeds: [editor, press]
decisions: [0002, 0011, 0013, 0014, 0020, 0023, 0026]
---

# writer

Drafts the broadcast script in spoken style and tags every factual sentence with claims.

## Contract

- `async def draft_script(rundown: Rundown) -> Script`: one `llm.complete("draft", ..., DraftSegment)` call per
  rundown item, run concurrently. Stores `script_lines` (order sequential across the briefing), `claims`
  (`verdict=pending`) and `claim_sources` in one transaction. An item with no usable sources, or whose segment fails
  (`WriterError` after one resample, or `LLMError`), is skipped (decision 0014). Raises `WriterError` only if no
  item has usable sources or none could be drafted.
- `Script`: briefing_id, lines[`DraftLine`: id, story_id, order, text, claims[`DraftClaim`: id, text, source_ids]].
- `async def draft_answer(question, story_title, sources, *, max_lines=3, max_chars=4000) -> list[CleanLine]`
  (`answer.py`, task 5.3): the anchor's short answer on the `answer` route, same schema and `validate_segment` as
  segments, one retry then `WriterError`; prompts `writer/answer_system.md` / `answer_user.md` (question escaped in
  `<question>`). Not covered -> one claimless line. `store_answer(briefing_id, story_id, question, lines)` stores
  `kind='answer'` lines at order >= 1000 with pending claims and `claim_sources`.
- `async def rewrite_line(line: DraftLine, feedback: Sequence[ClaimFeedback], round_no: int) -> DraftLine`: one
  `"draft"` call using the story's non-retracted sources and `prompts/writer/rewrite_user.md` (`$line`, `$feedback`).
  The output must be exactly one valid line (one resample, then `WriterError`). It keeps the line id and order, replaces
  the text, and replaces the line's claims with new `pending` ones carrying `rewrite_round` (decision 0013).
- `ClaimFeedback(text, verdict, reason)`: the Editor's feedback, in a Writer-owned type (no import of the Editor).
- Prompts: `prompts/writer/draft_system.md` (static rules) and `draft_user.md` (`$story_title`, `$target_words`,
  `$sources`). Sources go in `<source id="S<n>" outlet published>` blocks with `<`, `>` and `&` escaped, in the user turn only.
- Length: `target_seconds * writer_words_per_second` (2.5) words. Source text is capped at `writer_source_max_chars` (6000).
- `DraftLine.kind`: `script` (default) or `correction` (a Standards Desk template line, task 6.2).

- `async def summarize_story(story_id, title, sources: Sequence[SourceText], feedback=()) -> str` (`summary.py`,
  task 8.2): a ~60-word card summary for the Press feed (task "draft", prompts `writer/summary_system|user`);
  20 to 90 words, quotes under 15 words, resampled once with the problems, else `WriterError`. Not fact-checked.

## Invariants

- Paraphrase only; quotes under 15 words and attributed.
- No sentence with a factual statement goes out without at least one claim tag. Enforced by `validate_segment()`:
  every `factual` line has a claim, every claim cites a known `S<n>`, and quotes are at most 14 words.
- The Writer never writes `claim_evidence` (decision 0011).

## Current state

`draft_script()` done (task 2.1) in `app/writer/draft.py` and `prompts.py`. Spans: `writer/draft_script`
(briefing_id), with a child `writer/draft_segment` per story (attempts, lines, claims, words, problems).
`rewrite_line()` (task 2.3) in `rewrite.py`, span `writer/rewrite_line`. The draft prompt now requires attributing
a party's statements; in a live run 6 of 7 claims were approved on the first pass, and a rewrite fixed the other.
Tested with a fake Groq through `httpx.MockTransport` and on Postgres. One live smoke run (2026-11-18,
`openai/gpt-oss-20b`, 2 hand-written sources, 30 s target): 75/75 words, valid on the first try, ignored an injected
instruction. It states company-reported facts without attribution, which the Editor's `attributed` check flags as rewrite.

## Open questions

- (none)

## Changelog

- 2026-11-16: node created from the design doc.
- 2026-11-16: empty package scaffolded (task 0.1).
- 2026-11-17: `draft_script()` with claim tagging, validation + one resample, prompts in `prompts/writer/` (task 2.1).
- 2026-11-18: `rewrite_line()` + attribution rule in the draft prompt (task 2.3, decision 0013).
- 2026-11-18: a failed story is skipped instead of failing the briefing (decision 0014).
- 2026-11-19: `draft_answer()` / `store_answer()` for on-air answers (task 5.3).
- 2026-11-21: `DraftLine.kind` for correction lines (task 6.2, decision 0023).
- 2026-11-23: `summarize_story()` for Press feed cards (task 8.2, decision 0026).
