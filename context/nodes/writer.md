---
id: writer
type: component
status: planned
phase: 2
code: app/writer/
depends_on: [producer, editor, llm-gateway, data-model, archive]
feeds: [editor]
decisions: [0002]
---

# writer

Drafts the broadcast script in spoken style and tags every factual sentence with claims.

## Contract

- `async def draft_script(rundown: Rundown) -> Script`
- `async def rewrite_line(line: ScriptLine, rejected: list[ClaimVerdict]) -> ScriptLine`
- Each `ScriptLine` has text, story_id, order, and `claims: list[Claim]` (claim text + source ids it relied on).

## Invariants

- Paraphrase only; quotes under 15 words and attributed.
- No sentence with a factual statement goes out without at least one claim tag.

## Current state

Empty package scaffolded at `app/writer/` (docstring only, no public surface yet). Logic not started. Planned for phase 2.

## Open questions

- (none)

## Changelog

- 2026-11-16: node created from the design doc.
- 2026-11-16: empty package scaffolded (task 0.1).
