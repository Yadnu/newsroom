---
id: anchor
type: component
status: planned
phase: 4
code: app/anchor/
depends_on: [standards-desk, producer, archive]
feeds: [web]
decisions: [0004]
---

# anchor

Voice output. Streams the cleared script as speech and records audio timestamps per line.

## Contract

- `async def speak(script: ClearedScript, session: VoiceSession) -> None`
- `async def pause() / resume()` for barge-in
- Writes `audio_start_ms` and `audio_end_ms` on each script line.

## Invariants

- Pauses within 300 ms of detected caller speech.
- TTS provider sits behind an adapter selected by config.

## Current state

Empty package scaffolded at `app/anchor/` (docstring only, no public surface yet). Logic not started. Planned for phase 4.

## Open questions

- (none)

## Changelog

- 2026-11-16: node created from the design doc.
- 2026-11-16: empty package scaffolded (task 0.1).
