---
id: standards-desk
type: component
status: planned
phase: 5
code: app/standards_desk/
depends_on: [editor, caller, archive]
feeds: [anchor, producer]
decisions: []
---

# standards-desk

Guardrails on both ends: clears approved scripts for air and screens Caller input.

## Contract

- `def clear_for_air(judged: JudgedScript) -> ClearedScript` (blocks unapproved claims, verbatim copying, opinion stated as fact)
- `async def screen_caller(transcript: str) -> ScreenResult` (abusive, off-topic, prompt injection)

## Invariants

- Anchor accepts only `ClearedScript`; the type itself is the gate.
- Every block is logged with a reason.

## Current state

Empty package scaffolded at `app/standards_desk/` (docstring only, no public surface yet). Logic not started. Planned for phase 5.

## Open questions

- (none)

## Changelog

- 2026-11-16: node created from the design doc.
- 2026-11-16: empty package scaffolded (task 0.1).
