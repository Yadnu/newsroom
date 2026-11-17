---
id: writer
type: component
status: in-progress
phase: 2
code: app/writer/
depends_on: [producer, editor, llm-gateway, data-model, archive]
feeds: [editor]
decisions: [0002, 0011]
---

# writer

Drafts the broadcast script in spoken style and tags every factual sentence with claims.

## Contract

- `async def draft_script(rundown: Rundown) -> Script`: one `llm.complete("draft", ..., DraftSegment)` call per
  rundown item, run concurrently. Stores `script_lines` (order sequential across the briefing), `claims`
  (`verdict=pending`) and `claim_sources` in one transaction. Raises `WriterError` if a segment is still invalid
  after one resample, or if no item has usable (non-retracted) sources. An item with no usable sources is skipped.
- `Script`: briefing_id, lines[`DraftLine`: id, story_id, order, text, claims[`DraftClaim`: id, text, source_ids]].
- Planned (task 2.3): `async def rewrite_line(line: ScriptLine, rejected: list[ClaimVerdict]) -> ScriptLine`.
- Prompts: `prompts/writer/draft_system.md` (static rules) and `draft_user.md` (`$story_title`, `$target_words`,
  `$sources`). Sources go in `<source id="S<n>" outlet published>` blocks with `<`, `>` and `&` escaped, in the user turn only.
- Length: `target_seconds * writer_words_per_second` (2.5) words. Source text is capped at `writer_source_max_chars` (6000).

## Invariants

- Paraphrase only; quotes under 15 words and attributed.
- No sentence with a factual statement goes out without at least one claim tag. Enforced by `validate_segment()`:
  every `factual` line has a claim, every claim cites a known `S<n>`, and quotes are at most 14 words.
- The Writer never writes `claim_evidence` (decision 0011).

## Current state

`draft_script()` done (task 2.1) in `app/writer/draft.py` and `prompts.py`. Spans: `writer/draft_script`
(briefing_id), with a child `writer/draft_segment` per story (attempts, lines, claims, words, problems).
Tested with a fake Groq through `httpx.MockTransport` and on Postgres. Not yet run against a real model (no
`NEWSROOM_GROQ_API_KEY`), so prompt quality and length accuracy are unmeasured.

## Open questions

- (none)

## Changelog

- 2026-11-16: node created from the design doc.
- 2026-11-16: empty package scaffolded (task 0.1).
- 2026-11-17: `draft_script()` with claim tagging, validation + one resample, prompts in `prompts/writer/` (task 2.1).
