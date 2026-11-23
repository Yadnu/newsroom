---
id: anchor
type: component
status: in-progress
phase: 4
code: app/anchor/
depends_on: [standards-desk, producer, caller, archive]
feeds: [web]
decisions: [0004, 0016, 0017, 0020, 0028]
---

# anchor

Voice output. Streams the cleared script as speech and records audio timestamps per line.

## Contract

- `async def speak(script: ClearedScript, session: VoiceSession, *, tts=None, settings=None) -> SpeakReport`
  (`pipeline.py`): only a `ClearedScript` (else `TypeError`). Voices lines in order through a Pipecat 1.16 pipeline,
  writes `script_lines.audio_start_ms/audio_end_ms` for every line spoken (also on a partial run), and sets the
  briefing `aired` only when the last line played. `SpeakReport(briefing_id, lines: list[LineTiming(line_id, order,
  start_ms, end_ms)], audio_ms, pauses, completed)`. `AnchorError` if the TTS never ends a line.
- `VoiceSession` (`session.py`): `send_audio(pcm16)`, `send_event(dict)`, `close()`, `realtime`; barge-in
  `await session.pause()` (cuts the current line now) / `await session.resume()` (replays it from its start).
  Sinks: `WebSocketSession`, `WavFileSession(path, sample_rate)`, `MemorySession(realtime=False)`.
- Answers (task 5.3): `session.interject(cleared: ClearedScript, question_id)` queues a cleared answer (anything
  else raises `TypeError`); `speak()` voices it before the next briefing line, on the same pipeline and clock.
  `SpeakReport.answers` counts them. `line`/`line_end` events carry `kind` (`script`|`answer`) and `question_id`.
- Events: `start{briefing_id, sample_rate, lines}`, `line{line_id, order, text, start_ms}`, `line_end{line_id,
  end_ms}`, `paused{at_ms}`, `resumed{at_ms}`, `done{audio_ms, completed}`. Audio is PCM16 mono at `anchor_sample_rate`.
- WebSocket `/anchor/briefings/{id}/live` (`routes.py`): clears the stored briefing (`standards_desk.clear_stored`),
  streams it; client sends `{"type": "pause"|"resume"}`. Close codes 4404 unknown, 4409 nothing cleared, 4500 no TTS.
  The same socket carries push-to-talk mic audio for the Caller (`caller.live.CallIn`, task 5.1); sends are
  serialised in `WebSocketSession`, which also tracks `current_line_id`.
- `make_tts(settings)` (`tts.py`): `anchor_tts` = `cartesia` (needs `cartesia_api_key`, `cartesia_voice_id`; optional
  `cartesia_model`) or `fake` (`FakeTTSService`: silent PCM, 60 ms per word). `AnchorConfigError` if misconfigured.
- Settings: `anchor_sample_rate` 24000, `anchor_line_gap_ms` 300, `anchor_send_ahead_ms` 250, `anchor_line_timeout_s` 30.

- Word timings (task 8.4, decision 0028): `LineTiming.words` = `(word, start_ms, end_ms)` on the audio clock, from
  the TTS's word timestamps (`tts.take_words(tts, context_id)`; Cartesia via a recording subclass of Pipecat's
  service, the fake TTS evenly every `FAKE_MS_PER_WORD`); `word_spans()` clamps them inside the line and in
  order. `store_timings()` writes them to `script_lines.audio_words`.

## Invariants

- Speaks only a `ClearedScript`; the type is the gate (decision 0016).
- Line timestamps come from the audio clock and match the audio sent (decision 0017).
- A pause stops audio within one 20 ms slice; tested under 300 ms with the fake TTS and live over the WebSocket.
- TTS provider sits behind an adapter selected by config (decision 0004).

## Current state

Task 4.2 done in `app/anchor/` (`tts.py`, `session.py`, `pipeline.py`, `routes.py`). Spans `anchor/speak` (spoken,
audio_ms, pauses, completed, chars) > `anchor/line` (start_ms, end_ms, interrupted). Pipecat loguru output is cut to
warnings. Tests: `tests/test_anchor.py`, `tests/test_anchor_routes.py` (fake TTS), `tests/integration/test_anchor_db.py`
(CI). Live 2026-11-19 with Cartesia (voice Quentin): briefing `3873a08c` voiced to WAV, 5 lines, 28.9 s, WAV length =
last `end_ms`, silence exactly in the gaps; WebSocket run paused at 3 s (no audio after 300 ms) and resumed by
replaying line 0. Not yet: Cartesia cost accounting, word-level timestamps, the browser Player (4.3).

## Open questions

- (none)

## Changelog

- 2026-11-16: node created from the design doc.
- 2026-11-16: empty package scaffolded (task 0.1).
- 2026-11-19: Pipecat pipeline, Cartesia + fake adapters, audio-clock timestamps, live WebSocket (task 4.2, decision 0017).
- 2026-11-19: WebSocket carries Caller mic audio; pipeline shutdown is cancellation-safe (task 5.1).
- 2026-11-19: answers spoken as interjections between briefing lines (task 5.3).
- 2026-11-23: per-word audio timings from the TTS, stored in `script_lines.audio_words` (task 8.4, decision 0028).
