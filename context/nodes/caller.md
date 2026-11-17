---
id: caller
type: component
status: planned
phase: 5
code: app/caller/
depends_on: [archive]
feeds: [standards-desk, producer]
decisions: [0004]
---

# caller

Voice input. Streams listener audio to text and classifies intent.

## Contract

- `async def listen(session: VoiceSession) -> AsyncIterator[CallerQuestion]`
- `CallerQuestion`: transcript, intent (follow_up | background | off_topic), referenced story_id if any.

## Invariants

- STT provider sits behind an adapter selected by config.
- Raw audio is not stored by default.

## Current state

Empty package scaffolded at `app/caller/` (docstring only, no public surface yet). Logic not started. Planned for phase 5.

## Open questions

- (none)

## Changelog

- 2026-11-16: node created from the design doc.
- 2026-11-16: empty package scaffolded (task 0.1).
